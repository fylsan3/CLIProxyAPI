//go:build cpa_offline

package main

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	coreauth "github.com/router-for-me/CLIProxyAPI/v8/sdk/cliproxy/auth"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"
)

const observationFile = "/state/account-observation.json"

func accountIdentity(a *coreauth.Auth) map[string]string {
	t := tokenFromAuth(a)
	if strings.TrimSpace(t.AccountUUID) == "" {
		return nil
	}
	sum := sha256.Sum256([]byte(t.AccountUUID))
	return map[string]string{"key": hex.EncodeToString(sum[:]), "email": t.Email}
}
func readAccountObservation(a *coreauth.Auth) map[string]any {
	result := map[string]any{}
	b, e := os.ReadFile(observationFile)
	if e != nil || len(b) > 65536 || json.Unmarshal(b, &result) != nil {
		return nil
	}
	if result["account_key"] != accountIdentity(a)["key"] {
		return nil
	}
	return result
}
func cleanProfile(raw []byte, expected string) (map[string]any, bool) {
	var v map[string]any
	if json.Unmarshal(raw, &v) != nil {
		return nil, false
	}
	account, _ := v["account"].(map[string]any)
	if account["uuid"] != expected {
		return nil, false
	}
	result := map[string]any{}
	// Keep only reported subscription fields, not arbitrary profile data.
	for _, group := range []string{"account", "organization", ""} {
		m := v
		if group != "" {
			m, _ = v[group].(map[string]any)
		}
		for _, k := range []string{"subscription_type", "plan_type", "rate_limit_tier", "organization_type"} {
			if s, ok := m[k].(string); ok && len(s) > 0 && len(s) < 160 {
				result[k] = s
			}
		}
	}
	return result, true
}
func cleanUsage(raw []byte) (map[string]any, bool) {
	var v map[string]any
	if json.Unmarshal(raw, &v) != nil {
		return nil, false
	}
	result := map[string]any{}
	for _, k := range []string{"five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet", "seven_day_oauth_apps"} {
		item, ok := v[k].(map[string]any)
		if !ok {
			continue
		}
		entry := map[string]any{}
		if n, ok := item["utilization"].(float64); ok && n >= 0 && n <= 100 {
			entry["utilization"] = n
		}
		if s, ok := item["resets_at"].(string); ok {
			if _, e := time.Parse(time.RFC3339, s); e == nil {
				entry["resets_at"] = s
			}
		}
		if len(entry) > 0 {
			result[k] = entry
		}
	}
	return result, true
}
func (w *worker) updateAccount(out http.ResponseWriter, req *http.Request) {
	if !w.accountUpdating.CompareAndSwap(false, true) {
		localError(out, 409, "account_update_in_progress")
		return
	}
	defer w.accountUpdating.Store(false)
	if err := networkCheck(); err != nil {
		localError(out, 503, "account_network_unavailable")
		return
	}
	a, ok := w.manager.GetByID(w.authID())
	if !ok {
		localError(out, 409, "authorization_required")
		return
	}
	token := tokenFromAuth(a)
	identity := accountIdentity(a)
	if identity == nil {
		localError(out, 409, "account_identity_missing")
		return
	}
	result := readAccountObservation(a)
	if result == nil {
		result = map[string]any{"account_key": identity["key"]}
	}
	now := time.Now().UTC().Format(time.RFC3339)
	result["attempted_at"] = now
	type item struct {
		kind string
		raw  []byte
		err  error
	}
	ch := make(chan item, 2)
	var wg sync.WaitGroup
	for _, kind := range []string{"profile", "usage"} {
		wg.Add(1)
		go func(kind string) {
			defer wg.Done()
			ctx, cancel := context.WithTimeout(req.Context(), 15*time.Second)
			defer cancel()
			b, e := w.service.FetchContainerAccountResource(ctx, token.AccessToken, kind)
			ch <- item{kind, b, e}
		}(kind)
	}
	wg.Wait()
	close(ch)
	success := 0
	for item := range ch {
		previous, _ := result[item.kind].(map[string]any)
		if previous == nil {
			previous = map[string]any{}
		}
		previous["attempted_at"] = now
		if item.err != nil {
			previous["error"] = "upstream_query_failed"
		} else {
			var values map[string]any
			var valid bool
			if item.kind == "profile" {
				values, valid = cleanProfile(item.raw, token.AccountUUID)
			} else {
				values, valid = cleanUsage(item.raw)
			}
			if valid {
				previous = map[string]any{"values": values, "observed_at": now, "attempted_at": now, "source": "oauth_" + item.kind}
				success++
			} else {
				previous["error"] = "invalid_account_response"
			}
		}
		result[item.kind] = previous
	}
	b, e := json.Marshal(result)
	if e == nil {
		e = durableWrite(observationFile, b)
	}
	if e != nil {
		localError(out, 503, "account_observation_save_failed")
		return
	}
	response(out, 200, map[string]any{"ok": success == 2, "partial": success == 1, "account_observation": result})
}

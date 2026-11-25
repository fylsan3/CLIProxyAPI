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
	"regexp"
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
	for k := range v {
		if !regexp.MustCompile(`^(five_hour|seven_day(_[a-z0-9_]{1,48})?|iguana_necktie)$`).MatchString(k) {
			continue
		}
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
		for _, field := range []string{"limit_dollars", "used_dollars", "remaining_dollars"} {
			if n, ok := item[field].(float64); ok && n >= 0 {
				entry[field] = n
			}
		}
		if len(entry) > 0 {
			result[k] = entry
		}
	}
	// Scoped limits are quota facts, not arbitrary profile or credential material.
	if limits, ok := v["limits"].([]any); ok {
		clean := []any{}
		for _, raw := range limits {
			if len(clean) >= 64 {
				break
			}
			item, ok := raw.(map[string]any)
			if !ok {
				continue
			}
			kind, _ := item["kind"].(string)
			percent, ok := item["percent"].(float64)
			if kind != "weekly_scoped" || !ok || percent < 0 || percent > 100 {
				continue
			}
			scope, _ := item["scope"].(map[string]any)
			model, _ := scope["model"].(map[string]any)
			name, _ := model["display_name"].(string)
			if name == "" || len(name) > 120 {
				continue
			}
			value := map[string]any{"kind": kind, "percent": percent, "scope": map[string]any{"model": map[string]any{"display_name": name}}}
			if active, ok := item["is_active"].(bool); ok {
				value["is_active"] = active
			}
			if stamp, ok := item["resets_at"].(string); ok {
				if _, err := time.Parse(time.RFC3339, stamp); err == nil {
					value["resets_at"] = stamp
				}
			}
			clean = append(clean, value)
		}
		result["limits"] = clean
	}
	// Read-only grant facts. Never expose arbitrary upstream fields or claim a grant.
	if block, ok := v["cedar_ember"].(map[string]any); ok {
		clean := map[string]any{}
		for _, key := range []string{"eligible", "at_limit"} {
			if value, ok := block[key].(bool); ok {
				clean[key] = value
			}
		}
		if value, ok := block["cooldown_until"].(string); ok {
			if _, err := time.Parse(time.RFC3339, value); err == nil {
				clean["cooldown_until"] = value
			}
		}
		grants := []any{}
		if items, ok := block["grants"].([]any); ok {
			for _, raw := range items {
				if len(grants) >= 64 {
					break
				}
				item, ok := raw.(map[string]any)
				if !ok {
					continue
				}
				id, _ := item["id"].(string)
				if !regexp.MustCompile(`^[a-zA-Z0-9_-]{1,128}$`).MatchString(id) {
					continue
				}
				g := map[string]any{"id": id}
				for _, key := range []string{"resets_left", "resets_total"} {
					if n, ok := item[key].(float64); ok && n >= 0 && n <= 100000 && n == float64(int(n)) {
						g[key] = n
					}
				}
				for _, key := range []string{"paused", "usable_now", "use_requires_limit"} {
					if value, ok := item[key].(bool); ok {
						g[key] = value
					}
				}
				for _, key := range []string{"starts_at", "ends_at"} {
					if value, ok := item[key].(string); ok {
						if _, err := time.Parse(time.RFC3339, value); err == nil {
							g[key] = value
						}
					}
				}
				grants = append(grants, g)
			}
		}
		clean["grants"] = grants
		result["cedar_ember"] = clean
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

//go:build cpa_offline

package main

import (
	"encoding/json"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/accountheaders"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

// Explicit account-local test window. Disabled by default. Browser TLS and
// network probes are outside this HTTP boundary and never claimed as captured.
type captureWindow struct {
	Expires int64 `json:"expires"`
	Enabled bool  `json:"enabled"`
}

func captureWindowActive(root string) bool {
	path := filepath.Join(root, "capture-window.json")
	if safeFile(path) != nil {
		return false
	}
	b, e := os.ReadFile(path)
	var c captureWindow
	return e == nil && json.Unmarshal(b, &c) == nil && c.Enabled && c.Expires > time.Now().Unix()
}

var headerAuditMu sync.Mutex

func captureAuditStatus(root string) map[string]any {
	headerAuditMu.Lock()
	defer headerAuditMu.Unlock()
	result := map[string]any{}
	b, e := os.ReadFile(filepath.Join(root, "header-audit.json"))
	if e == nil {
		_ = json.Unmarshal(b, &result)
	}
	result["capture_active"] = captureWindowActive(root)
	result["scope"] = "go_account_http_only"
	result["current_policy_version"] = accountheaders.Version()
	result["current_policy_sha256"] = accountheaders.Digest()
	result["capture_format"] = "executor_before_policy_and_final_wire"
	return result
}
func recordCaptureIssue(root, code string) {
	headerAuditMu.Lock()
	defer headerAuditMu.Unlock()
	v := map[string]any{}
	b, _ := os.ReadFile(filepath.Join(root, "header-audit.json"))
	_ = json.Unmarshal(b, &v)
	v["capture_issue"] = code
	v["updated_at"] = time.Now().UTC().Format(time.RFC3339)
	_ = durableWrite(filepath.Join(root, "header-audit.json"), mustArchiveJSON(v))
}

// Compare actual wire observations with the immutable sending policy.
// Independent migration fixtures test the policy itself. Never include
// credentials, unknown header values, URLs with query strings or bodies in alerts.
func auditHeaderNames(path string, wire []map[string]any) ([]string, []string) {
	h := http.Header{}
	for _, row := range wire {
		name, _ := row["name"].(string)
		values, _ := row["values"].([]string)
		for _, v := range values {
			h.Add(name, v)
		}
	}
	op, ok := accountheaders.ForPath(path)
	if !ok {
		return []string{"unclassified_endpoint"}, nil
	}
	osName, arch := containerPlatformHeaders()
	rule := accountheaders.Resolve(op.Profile, osName, arch)
	expected, absent := rule.Set, rule.Delete
	mismatches := []string{}
	unknown := []string{}
	for k, v := range expected {
		values := h.Values(k)
		if len(values) != 1 || values[0] != v {
			mismatches = append(mismatches, k)
		}
	}
	for _, k := range absent {
		if len(h.Values(k)) != 0 {
			mismatches = append(mismatches, k)
		}
	}
	// Dynamic/native fields are classified, not forced into the model override set.
	for name := range h {
		k := strings.ToLower(name)
		if _, ok := expected[k]; !ok && !accountheaders.Known(k) {
			unknown = append(unknown, k)
		}
	}
	sort.Strings(mismatches)
	sort.Strings(unknown)
	return mismatches, unknown
}
func recordHeaderAudit(root, id, path string, wire []map[string]any, writeOK bool) {
	mismatches, unknown := auditHeaderNames(path, wire)
	headerAuditMu.Lock()
	defer headerAuditMu.Unlock()
	v := map[string]any{}
	b, _ := os.ReadFile(filepath.Join(root, "header-audit.json"))
	_ = json.Unmarshal(b, &v)
	count, _ := v["observed_requests"].(float64)
	v["observed_requests"] = int(count) + 1
	v["last_archive"] = id
	v["last_path"] = path
	v["policy_version"] = accountheaders.Version()
	v["policy_sha256"] = accountheaders.Digest()
	v["updated_at"] = time.Now().UTC().Format(time.RFC3339)
	v["last_write_ok"] = writeOK
	if len(mismatches) > 0 || len(unknown) > 0 || !writeOK {
		alerts, _ := v["alerts"].([]any)
		alerts = append(alerts, map[string]any{"archive": id, "path": path, "at": v["updated_at"], "mismatched_headers": mismatches, "unclassified_headers": unknown, "write_ok": writeOK})
		if len(alerts) > 32 {
			alerts = alerts[len(alerts)-32:]
		}
		v["alerts"] = alerts
	}
	_ = durableWrite(filepath.Join(root, "header-audit.json"), mustArchiveJSON(v))
}

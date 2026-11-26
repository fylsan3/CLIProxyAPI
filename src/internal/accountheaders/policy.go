// Package accountheaders owns account HTTP policy. Its immutable source is shared
// by the final sender, wire audit and generated redacted-export snapshot.
package accountheaders

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"strings"
)

// PolicyJSON is the single editable policy source. Existing identity declarations
// are retained for migration equivalence; they do not describe the Go runtime.
const PolicyJSON = `{
  "version": "account-egress-4-single-source",
  "variables": {
    "client_version": "2.1.331"
  },
  "profiles": {
    "model": {
      "set": {
        "user-agent": "claude-cli/${client_version} (external, sdk-cli)",
        "x-stainless-os": "${platform_os}",
        "x-stainless-arch": "${platform_arch}",
        "x-stainless-runtime": "node",
        "x-stainless-runtime-version": "v26.12.1",
        "x-stainless-lang": "js",
        "x-stainless-package-version": "0.128.0",
        "x-app": "cli",
        "anthropic-dangerous-direct-browser-access": "true",
        "anthropic-version": "2023-06-01",
        "accept": "application/json",
        "accept-encoding": "gzip, deflate, br, zstd"
      }
    },
    "token": {
      "set": {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "user-agent": "axios/1.15.2",
        "accept-encoding": "gzip, compress, deflate, br",
        "connection": "keep-alive"
      },
      "delete": [
        "cache-control"
      ],
      "close": false
    },
    "profile": {
      "extends": "token",
      "set": {
        "user-agent": "claude-code/${client_version}",
        "cache-control": "no-cache"
      },
      "delete": []
    },
    "roles": {
      "extends": "token",
      "set": {
        "user-agent": "claude-code/${client_version}"
      },
      "delete": [
        "content-type",
        "cache-control"
      ]
    },
    "usage": {
      "extends": "token",
      "set": {
        "user-agent": "claude-cli/${client_version} (external, sdk-cli)",
        "anthropic-beta": "oauth-2025-04-20"
      },
      "delete": [
        "cache-control"
      ]
    },
    "native_usage": {
      "extends": "profile",
      "delete": []
    }
  },
  "operations": [
    {
      "method": "POST",
      "host": "api.anthropic.com",
      "path": "/v1/messages",
      "kind": "model",
      "profile": "model"
    },
    {
      "method": "POST",
      "host": "api.anthropic.com",
      "path": "/v1/messages/count_tokens",
      "kind": "model",
      "profile": "model"
    },
    {
      "method": "POST",
      "host": "platform.claude.com",
      "path": "/v1/oauth/token",
      "kind": "oauth",
      "profile": "token"
    },
    {
      "method": "GET",
      "host": "api.anthropic.com",
      "path": "/api/oauth/profile",
      "kind": "oauth",
      "profile": "profile"
    },
    {
      "method": "GET",
      "host": "api.anthropic.com",
      "path": "/api/oauth/claude_cli/roles",
      "kind": "oauth",
      "profile": "roles"
    },
    {
      "method": "GET",
      "host": "api.anthropic.com",
      "path": "/api/oauth/usage",
      "kind": "oauth",
      "profile": "usage"
    }
  ],
  "known_passthrough_headers": [
    "host",
    "content-length",
    "transfer-encoding",
    "content-type",
    "authorization",
    "x-api-key",
    "accept",
    "accept-encoding",
    "connection",
    "cache-control",
    "anthropic-beta",
    "x-claude-code-session-id",
    "x-client-request-id",
    "x-stainless-retry-count",
    "x-stainless-timeout"
  ]
}`

type Rule struct {
	Extends string            `json:"extends"`
	Set     map[string]string `json:"set"`
	Delete  []string          `json:"delete"`
	Close   *bool             `json:"close"`
}
type Operation struct{ Method, Host, Path, Kind, Profile string }
type document struct {
	Version    string            `json:"version"`
	Variables  map[string]string `json:"variables"`
	Profiles   map[string]Rule   `json:"profiles"`
	Operations []Operation       `json:"operations"`
	Known      []string          `json:"known_passthrough_headers"`
}

var policy = func() document {
	var d document
	if err := json.Unmarshal([]byte(PolicyJSON), &d); err != nil {
		panic(err)
	}
	return d
}()

func Version() string         { return policy.Version }
func Digest() string          { s := sha256.Sum256([]byte(PolicyJSON)); return hex.EncodeToString(s[:]) }
func Operations() []Operation { return append([]Operation(nil), policy.Operations...) }
func Known(name string) bool {
	for _, k := range policy.Known {
		if k == strings.ToLower(name) {
			return true
		}
	}
	return false
}
func ForPath(path string) (Operation, bool) {
	for _, op := range policy.Operations {
		if op.Path == path {
			return op, true
		}
	}
	return Operation{}, false
}
func ForRequest(r *http.Request) (Operation, bool) {
	if r == nil || r.URL == nil || r.URL.Scheme != "https" || r.URL.User != nil {
		return Operation{}, false
	}
	for _, op := range policy.Operations {
		if r.Method == op.Method && r.URL.Host == op.Host && r.URL.Path == op.Path {
			return op, true
		}
	}
	return Operation{}, false
}
func Resolve(name, platformOS, platformArch string) Rule {
	raw, ok := policy.Profiles[name]
	if !ok {
		panic("unknown account header profile")
	}
	r := Rule{Set: map[string]string{}}
	if raw.Extends != "" {
		r = Resolve(raw.Extends, platformOS, platformArch)
	}
	for k, v := range raw.Set {
		for key, value := range policy.Variables {
			v = strings.ReplaceAll(v, "${"+key+"}", value)
		}
		v = strings.ReplaceAll(v, "${platform_os}", platformOS)
		v = strings.ReplaceAll(v, "${platform_arch}", platformArch)
		r.Set[k] = v
	}
	if raw.Delete != nil {
		r.Delete = append([]string{}, raw.Delete...)
	}
	if raw.Close != nil {
		v := *raw.Close
		r.Close = &v
	}
	for _, k := range r.Delete {
		delete(r.Set, k)
	}
	return r
}
func Apply(r *http.Request, rule Rule) {
	if r.Header == nil {
		r.Header = make(http.Header)
	}
	for name := range r.Header {
		k := strings.ToLower(name)
		_, managed := rule.Set[k]
		for _, absent := range rule.Delete {
			if k == absent {
				managed = true
			}
		}
		if managed {
			delete(r.Header, name)
		}
	}
	for k, v := range rule.Set {
		r.Header.Set(k, v)
	}
	if rule.Close != nil {
		r.Close = *rule.Close
	}
}

// ApplyNativeOAuth preserves the non-container CPA path, including its pre-final
// usage defaults. Containers defer ALL managed OAuth headers to providerTransport.
func ApplyNativeOAuth(r *http.Request) {
	op, ok := ForRequest(r)
	if !ok || op.Kind != "oauth" {
		return
	}
	profile := op.Profile
	if profile == "usage" {
		profile = "native_usage"
	}
	Apply(r, Resolve(profile, "", ""))
}

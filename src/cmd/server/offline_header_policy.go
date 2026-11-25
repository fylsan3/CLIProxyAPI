//go:build cpa_offline

package main

import (
	"net/http"
	"strings"
)

// This is the only final HTTP header policy. Browser TLS is tunneled intact:
// it is explicitly not a request generated or re-identified by this policy.
const accountHeaderPolicyVersion = "account-egress-3-usage-headers"

type accountOperation struct{ Method, Host, Path, Kind string }

var accountOperations = []accountOperation{
	{"POST", "api.anthropic.com", "/v1/messages", "model"},
	{"POST", "api.anthropic.com", "/v1/messages/count_tokens", "model"},
	{"POST", "platform.claude.com", "/v1/oauth/token", "oauth"},
	{"GET", "api.anthropic.com", "/api/oauth/profile", "oauth"},
	{"GET", "api.anthropic.com", "/api/oauth/claude_cli/roles", "oauth"},
	{"GET", "api.anthropic.com", "/api/oauth/usage", "oauth"},
}

func accountOperationFor(r *http.Request) (accountOperation, bool) {
	if r == nil || r.URL == nil || r.URL.Scheme != "https" || r.URL.User != nil {
		return accountOperation{}, false
	}
	for _, op := range accountOperations {
		if r.Method == op.Method && r.URL.Host == op.Host && r.URL.Path == op.Path {
			return op, true
		}
	}
	return accountOperation{}, false
}

// Preserved manual model overrides; only the two platform fields are derived
// from the previously validated persistent container baseline.
func modelHeaderOverrides() map[string]string {
	platformOS, platformArch := containerPlatformHeaders()
	return map[string]string{
		"user-agent":                                "claude-cli/2.1.331 (external, sdk-cli)",
		"x-stainless-os":                            platformOS,
		"x-stainless-arch":                          platformArch,
		"x-stainless-runtime":                       "node",
		"x-stainless-runtime-version":               "v26.12.1",
		"x-stainless-lang":                          "js",
		"x-stainless-package-version":               "0.128.0",
		"x-app":                                     "cli",
		"anthropic-dangerous-direct-browser-access": "true",
		"anthropic-version":                         "2023-06-01",
		"accept":                                    "application/json",
		"accept-encoding":                           "gzip, deflate, br, zstd",
	}
}

func replaceAccountHeaders(h http.Header, values map[string]string) {
	for name := range h {
		if _, ok := values[strings.ToLower(name)]; ok {
			delete(h, name)
		}
	}
	for name, value := range values {
		h.Set(name, value)
	}
}

func applyProviderHeaders(r *http.Request) {
	op, ok := accountOperationFor(r)
	if !ok {
		return
	}
	if op.Kind == "model" {
		replaceAccountHeaders(r.Header, modelHeaderOverrides())
		return
	}
	if op.Path == "/api/oauth/usage" {
		if r.Header == nil {
			r.Header = make(http.Header)
		}
		replaceAccountHeaders(r.Header, map[string]string{
			"user-agent":     "claude-cli/2.1.331 (external, sdk-cli)",
			"content-type":   "application/json",
			"connection":     "keep-alive",
			"anthropic-beta": "oauth-2025-04-20",
		})
		for name := range r.Header {
			if strings.EqualFold(name, "Cache-Control") {
				delete(r.Header, name)
			}
		}
		// The native OAuth client sets Close; clear it as well as the header.
		// The transport's idle connection pooling policy remains independent.
		r.Close = false
		return
	}
	// Other OAuth operations retain CPA's native headers and connection policy.
}

func applyNetworkCheckHeaders(r *http.Request, kind string) {
	// Probes have no account credential, cookie, customer payload or model headers.
	r.Header = make(http.Header)
	r.Header.Set("User-Agent", "CPA-Network-Check/1")
	r.Header.Set("Connection", "close")
	if kind == "location" {
		r.Header.Set("Accept", "application/json")
	}
	r.Close = true
}

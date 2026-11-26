//go:build cpa_offline

package main

import (
	"github.com/router-for-me/CLIProxyAPI/v8/internal/accountheaders"
	"net/http"
)

// The account transport is the final owner. Endpoint-specific policy lives once
// in internal/accountheaders, not in OAuth call sites or audit expectations.
var accountHeaderPolicyVersion = accountheaders.Version()

type accountOperation = accountheaders.Operation

var accountOperations = accountheaders.Operations()

func accountOperationFor(r *http.Request) (accountOperation, bool) {
	return accountheaders.ForRequest(r)
}
func modelHeaderOverrides() map[string]string {
	osName, arch := containerPlatformHeaders()
	return accountheaders.Resolve("model", osName, arch).Set
}
func applyProviderHeaders(r *http.Request) {
	op, ok := accountOperationFor(r)
	if !ok {
		return
	}
	osName, arch := containerPlatformHeaders()
	accountheaders.Apply(r, accountheaders.Resolve(op.Profile, osName, arch))
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

//go:build cpa_offline

package claude

import "net/http"

// NewContainerAuth keeps native OAuth requests and scope selection while using
// the account's verified, proxy-bound transport. It never installs a TLS bypass.
func NewContainerAuth(client *http.Client) *ClaudeAuth {
	return &ClaudeAuth{httpClient: client, authorizeScope: resolveClaudeAuthorizeScope(nil)}
}

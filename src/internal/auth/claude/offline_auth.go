//go:build cpa_offline

package claude

import "net/http"

// NewOfflineAuth injects the closed-lab transport without changing production constructors.
// The binary using it must reject real credentials and have no external network access.
func NewOfflineAuth(client *http.Client) *ClaudeAuth {
	return &ClaudeAuth{httpClient: client, authorizeScope: ClaudeOAuthScope}
}

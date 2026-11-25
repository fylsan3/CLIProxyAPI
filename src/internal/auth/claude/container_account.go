//go:build cpa_offline

package claude

import (
	"context"
	"fmt"
)

// Uses the original OAuth transport and response limits. No caller-selected URL.
func (o *ClaudeAuth) FetchContainerAccountResource(ctx context.Context, token, kind string) ([]byte, error) {
	endpoint := ProfileURL
	if kind == "usage" {
		endpoint = "https://api.anthropic.com/api/oauth/usage"
	} else if kind != "profile" {
		return nil, fmt.Errorf("unsupported account resource")
	}
	return o.fetchOAuthControlPlaneJSON(ctx, endpoint, token, kind)
}

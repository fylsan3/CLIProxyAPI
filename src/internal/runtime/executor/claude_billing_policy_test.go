package executor

import (
	"context"
	"strings"
	"testing"

	"github.com/MoeForge/moego/ojson"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/accountheaders"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/config"
)

func TestClaudeBillingUsesAccountPolicy(t *testing.T) {
	if accountheaders.ClientVersion() != "2.1.331" {
		t.Fatal("unexpected policy client version")
	}
	cfg := &config.Config{}
	cfg.ClaudeHeaderDefaults.UserAgent = "claude-cli/2.1.321 (external, cli)"
	body := []byte(`{"model":"claude-opus-4-6","messages":[{"role":"user","content":"x"}]}`)
	doc := ojson.NewDoc(body)
	headers := []string{
		claudeCCHFallbackBillingHeader(context.Background(), cfg, body, "cli"),
		claudeCCHFallbackBillingHeaderDoc(context.Background(), cfg, doc, "cli"),
	}
	rewritten := checkSystemInstructionsWithMode(body, false)
	headers = append(headers, ojson.GetBytes(rewritten, "system.0.text").String())
	doc = ojson.NewDoc(body)
	checkSystemInstructionsWithModeDoc(doc, false)
	headers = append(headers, doc.Get("system.0.text").String())
	for _, header := range headers {
		if !strings.HasPrefix(header, "x-anthropic-billing-header: cc_version=2.1.331.49f;") {
			t.Fatalf("unexpected billing text: %s", header)
		}
	}
	for _, name := range []string{"model", "profile", "roles", "usage"} {
		ua := accountheaders.Resolve(name, "Linux", "arm64").Set["user-agent"]
		if !strings.Contains(ua, "/"+accountheaders.ClientVersion()) {
			t.Fatalf("%s header version differs: %s", name, ua)
		}
	}
}

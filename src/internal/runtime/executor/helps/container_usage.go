package helps

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"github.com/router-for-me/CLIProxyAPI/v8/sdk/cliproxy/usage"
	"net/http"
	"sync"
)

const ContainerUsageHeader = "X-Offline-Native-Usage"

type containerUsageKey struct{}

// Only accounting facts cross the private bridge, never account/session identity.
type ContainerUsageCapture struct {
	mu     sync.Mutex
	detail *usage.Detail
}

func WithContainerUsageCapture(ctx context.Context, c *ContainerUsageCapture) context.Context {
	return context.WithValue(ctx, containerUsageKey{}, c)
}
func captureContainerUsage(ctx context.Context, detail usage.Detail) {
	if ctx == nil {
		return
	}
	if c, ok := ctx.Value(containerUsageKey{}).(*ContainerUsageCapture); ok {
		c.mu.Lock()
		c.detail = &detail
		c.mu.Unlock()
	}
}
func (c *ContainerUsageCapture) Encoded() string {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.detail == nil {
		return ""
	}
	b, e := json.Marshal(c.detail)
	if e != nil || len(b) > 32768 {
		return ""
	}
	return base64.RawStdEncoding.EncodeToString(b)
}
func ReadContainerUsage(r *http.Response) (usage.Detail, bool) {
	value := r.Trailer.Get(ContainerUsageHeader)
	if value == "" {
		value = r.Header.Get(ContainerUsageHeader)
	}
	var detail usage.Detail
	if len(value) == 0 || len(value) > 44000 {
		return detail, false
	}
	b, e := base64.RawStdEncoding.DecodeString(value)
	if e != nil || json.Unmarshal(b, &detail) != nil {
		return detail, false
	}
	return detail, true
}

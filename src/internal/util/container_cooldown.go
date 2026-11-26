package util

import (
	"math"
	"net/http"
	"strconv"
	"strings"
	"time"
)

// These receipts belong only to the private worker-to-central hop. Both public
// request and response filters exclude X-Offline-* headers.
const ContainerCooldownBridge = "X-Offline-Cooldown-Bridge"
const ContainerRetryAt = "X-Offline-Retry-At"
const ContainerCredentialScope = "X-Offline-Credential-Scope"
const ContainerTransientRateLimit = "X-Offline-Transient-Rate-Limit"

type ContainerCooldownHint struct {
	RetryAt            time.Time
	CredentialScoped   bool
	TransientRateLimit bool
}

func (h ContainerCooldownHint) RetryAfter() *time.Duration {
	if h.RetryAt.IsZero() {
		return nil
	}
	d := time.Until(h.RetryAt)
	if d < 0 {
		d = 0
	}
	return &d
}

func ReadContainerCooldownHint(h http.Header, now time.Time) ContainerCooldownHint {
	var hint ContainerCooldownHint
	if h.Get(ContainerCooldownBridge) == "1" {
		hint.RetryAt, _ = time.Parse(time.RFC3339Nano, h.Get(ContainerRetryAt))
		hint.CredentialScoped = h.Get(ContainerCredentialScope) == "true"
		hint.TransientRateLimit = !hint.CredentialScoped && h.Get(ContainerTransientRateLimit) == "true"
		return hint
	}
	// Older workers have no typed receipt. Recover only explicit timing headers;
	// never guess credential scope from an arbitrary message body.
	for _, p := range []struct {
		name string
		unit time.Duration
	}{{"Retry-After-Ms", time.Millisecond}, {"Retry-After", time.Second}} {
		raw := strings.TrimSpace(h.Get(p.name))
		if raw == "" {
			continue
		}
		v, err := strconv.ParseFloat(raw, 64)
		if err == nil && !math.IsNaN(v) && !math.IsInf(v, 0) && v >= 0 && v < float64(math.MaxInt64)/float64(p.unit) {
			hint.RetryAt = now.Add(time.Duration(v * float64(p.unit)))
			return hint
		}
		if p.name == "Retry-After" {
			if at, err := http.ParseTime(raw); err == nil {
				hint.RetryAt = at
				return hint
			}
		}
	}
	return hint
}

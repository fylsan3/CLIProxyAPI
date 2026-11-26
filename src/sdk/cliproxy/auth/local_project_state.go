package auth

import "time"

// Preserve native error classification across the private container boundary.
// The bridge must not invent its own interpretation of subscription limits.
func LocalProjectErrorHints(err error) (*time.Duration, bool, bool) {
	return retryAfterFromError(err), isCredentialScopedError(err), isTransientRateLimitError(err)
}

// LocalProjectDispatchView is a read-only projection of the actual selector predicate.
// It does not select, rotate, reset, or expose any credential fields.
func LocalProjectDispatchView(a *Auth, model string, now time.Time) map[string]any {
	blocked, reason, next := isAuthBlockedForModel(a, model, now)
	label := "eligible"
	if blocked {
		switch reason {
		case blockReasonCooldown:
			label = "cooldown"
		case blockReasonDisabled:
			label = "disabled"
		default:
			label = "unavailable"
		}
	}
	result := map[string]any{"eligible": !blocked, "reason": label, "observed_at": now.UTC().Format(time.RFC3339Nano)}
	if !next.IsZero() {
		result["retry_after"] = next.UTC().Format(time.RFC3339Nano)
	}
	return result
}

// Read the original configured/default worker count instead of copying its constant.
func (m *Manager) LocalProjectRefreshWorkers() int { return m.refreshWorkers() }

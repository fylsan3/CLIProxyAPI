//go:build cpa_offline

package auth

import (
	"context"
	"time"
)

// These lab-only entry points reuse CPA decisions, not replacement algorithms.
func (m *Manager) OfflineRefreshDue(a *Auth, now time.Time) bool { return m.shouldRefresh(a, now) }
func (m *Manager) OfflineRefreshIfDue(ctx context.Context, id string) error {
	a, ok := m.GetByID(id)
	if !ok || !m.shouldRefresh(a, time.Now()) {
		return nil
	}
	_, err := m.refreshAuthForRequest(ctx, id, "")
	return err
}
func OfflineDispatchIssue(a *Auth, model string, now time.Time) string {
	blocked, _, _ := isAuthBlockedForModel(a, model, now)
	if !blocked {
		return ""
	}
	if a == nil {
		return "authorization_required"
	}
	if a.Disabled || a.Status == StatusDisabled {
		return "account_disabled"
	}
	if exp, ok := a.AccessTokenExpirationTime(); ok && !exp.After(now) {
		return "credential_expired"
	}
	if hasUnauthorizedAuthFailure(a) {
		return "credential_rejected"
	}
	return "account_unavailable"
}

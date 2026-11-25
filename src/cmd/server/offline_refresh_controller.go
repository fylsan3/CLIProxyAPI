//go:build cpa_offline

package main

import (
	"context"
	"errors"
	"os"
	"sync"
	"sync/atomic"
	"time"

	claudeauth "github.com/router-for-me/CLIProxyAPI/v8/internal/auth/claude"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/registry"
	native "github.com/router-for-me/CLIProxyAPI/v8/internal/runtime/executor"
	coreauth "github.com/router-for-me/CLIProxyAPI/v8/sdk/cliproxy/auth"
	execution "github.com/router-for-me/CLIProxyAPI/v8/sdk/cliproxy/executor"
)

// CPA marks these runtime fields json:"-". This explicit private checkpoint is
// a container adaptation, not a claim that CPA's default store persists them.
type renewalState struct {
	RequiresSignIn        bool            `json:"requires_sign_in"`
	RefreshError          *coreauth.Error `json:"refresh_error,omitempty"`
	RejectedAccessToken   string          `json:"rejected_access_token,omitempty"`
	RejectedRefreshToken  string          `json:"rejected_refresh_token,omitempty"`
	RefreshFailures       int             `json:"refresh_failures"`
	RenewalVerified       bool            `json:"renewal_verified"`
	LastRenewalVerifiedAt time.Time       `json:"last_renewal_verified_at"`
}
type accountStore struct {
	mu             sync.Mutex
	owner          string
	persist        func(*tokenRecord) error
	failed         atomic.Bool
	lastGeneration uint64
}

func (s *accountStore) List(context.Context) ([]*coreauth.Auth, error) { return nil, nil }
func (s *accountStore) Delete(context.Context, string) error {
	return errors.New("offline_delete_unsupported")
}
func (s *accountStore) Save(ctx context.Context, a *coreauth.Auth) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if a.ID != "offline-"+s.owner || a.Provider != "claude" {
		return "", errors.New("credential_owner_mismatch")
	}
	token := tokenFromAuth(a)
	if !validToken(s.owner, token) {
		return "", errors.New("offline_credential_required")
	}
	if a.Generation < s.lastGeneration {
		return authFile, nil
	}
	record := &tokenRecord{Owner: s.owner, Revision: int(a.CredentialVersion), Token: token, Auth: a.Clone(), Renewal: &renewalState{
		RequiresSignIn: a.RequiresSignIn, RefreshError: a.RefreshError, RejectedAccessToken: a.RejectedAccessToken,
		RejectedRefreshToken: a.RejectedRefreshToken, RefreshFailures: a.RefreshFailures,
		RenewalVerified: a.RenewalVerified, LastRenewalVerifiedAt: a.LastRenewalVerifiedAt}}
	err := s.persist(record)
	s.failed.Store(err != nil)
	if err == nil {
		s.lastGeneration = a.Generation
	}
	return authFile, err
}
func tokenFromAuth(a *coreauth.Auth) claudeauth.ClaudeTokenData {
	read := func(k string) string { return claudeauth.ReadMetadataString(&a.Metadata, k) }
	return claudeauth.ClaudeTokenData{AccessToken: read("access_token"), RefreshToken: read("refresh_token"), Expire: read("expired"), Email: read("email"), AccountUUID: read("account_uuid"), OrganizationUUID: read("organization_uuid"), OrganizationName: read("organization_name")}
}
func (w *worker) authID() string { return "offline-" + w.owner }
func (w *worker) setup() error {
	persist := w.persist
	if persist == nil {
		persist = saveRecord
	}
	w.store = &accountStore{owner: w.owner, persist: persist}
	w.manager = coreauth.NewManager(w.store, nil, nil)
	w.manager.SetRetryConfig(0, 0, 1)
	w.manager.RegisterExecutor(&refreshExecutor{ClaudeExecutor: w.executor, w: w})
	if w.record != nil {
		return w.register(w.record)
	}
	return nil
}
func (w *worker) register(record *tokenRecord) error {
	if record.Owner != w.owner || !validToken(w.owner, record.Token) {
		return errors.New("offline_credential_required")
	}
	a := record.Auth
	if a == nil {
		t := record.Token
		a = &coreauth.Auth{ID: w.authID(), Provider: "claude", Status: coreauth.StatusActive, CredentialVersion: uint64(record.Revision), NextRefreshAfter: record.NextRefresh, Metadata: map[string]any{
			"access_token": t.AccessToken, "refresh_token": t.RefreshToken, "expired": t.Expire, "email": t.Email, "account_uuid": t.AccountUUID,
			"organization_uuid": t.OrganizationUUID, "organization_name": t.OrganizationName, "cloak_mode": "never"}}
	} else {
		a = a.Clone()
		if a.ID != w.authID() || a.Provider != "claude" || !validToken(w.owner, tokenFromAuth(a)) {
			return errors.New("credential_owner_mismatch")
		}
	}
	if r := record.Renewal; r != nil {
		a.RequiresSignIn = r.RequiresSignIn
		a.RefreshError = r.RefreshError
		a.RejectedAccessToken = r.RejectedAccessToken
		a.RejectedRefreshToken = r.RejectedRefreshToken
		a.RefreshFailures = r.RefreshFailures
		a.RenewalVerified = r.RenewalVerified
		a.LastRenewalVerifiedAt = r.LastRenewalVerifiedAt
	}
	models := registry.GetClaudeModels()
	if os.Getenv("CPA_PROVIDER") == "mock-claude" {
		models = []*registry.ModelInfo{{ID: "claude-sonnet-4-5"}}
	}
	registry.GetGlobalRegistry().RegisterClient(a.ID, "claude", models)
	_, err := w.manager.Register(coreauth.WithSkipPersist(context.Background()), a)
	return err
}

// Only acquisition transport is replaced by a Unix-socket fixture. The manager
// owns refresh locking, failure classification, merging, and publication.
type refreshExecutor struct {
	*native.ClaudeExecutor
	w *worker
}

func (e *refreshExecutor) Refresh(ctx context.Context, a *coreauth.Auth) (*coreauth.Auth, error) {
	if err := networkCheck(); err != nil {
		return nil, err
	}
	token := tokenFromAuth(a)
	if !validToken(e.w.owner, token) {
		return nil, errors.New("offline_credential_required")
	}
	e.w.renewing.Store(true)
	defer e.w.renewing.Store(false)
	var updated *claudeauth.ClaudeTokenData
	var err error
	if e.w.renew != nil {
		updated, err = e.w.renew(ctx, token.RefreshToken)
	} else {
		updated, err = e.w.service.RefreshTokensWithRetry(ctx, token.RefreshToken, 3)
	}
	if err != nil {
		return nil, err
	}
	if updated == nil || !validToken(e.w.owner, *updated) {
		return nil, errors.New("offline_credential_required")
	}
	// Clone the map: CPA's Auth.Clone shares Metadata with immutable snapshots.
	metadata := make(map[string]any, len(a.Metadata))
	for k, v := range a.Metadata {
		metadata[k] = v
	}
	a.Metadata = metadata
	a.Metadata["access_token"] = updated.AccessToken
	a.Metadata["refresh_token"] = updated.RefreshToken
	a.Metadata["expired"] = updated.Expire
	for k, v := range map[string]string{"email": updated.Email, "account_uuid": updated.AccountUUID, "organization_uuid": updated.OrganizationUUID, "organization_name": updated.OrganizationName} {
		if v != "" {
			a.Metadata[k] = v
		}
	}
	a.Metadata["last_refresh"] = time.Now().Format(time.RFC3339)
	return a, nil
}

// The native manager retains credential/retry state; each execution gets its config snapshot.
func (e *refreshExecutor) requestExecutor(ctx context.Context) *native.ClaudeExecutor {
	if cfg := coreauth.RequestScopedErrorConfigFromContext(ctx); cfg != nil {
		return e.ClaudeExecutor.WithConfigSnapshot(cfg)
	}
	return e.ClaudeExecutor
}
func (e *refreshExecutor) Execute(ctx context.Context, a *coreauth.Auth, r execution.Request, o execution.Options) (execution.Response, error) {
	return e.requestExecutor(ctx).Execute(ctx, a, r, o)
}
func (e *refreshExecutor) ExecuteStream(ctx context.Context, a *coreauth.Auth, r execution.Request, o execution.Options) (*execution.StreamResult, error) {
	return e.requestExecutor(ctx).ExecuteStream(ctx, a, r, o)
}
func (e *refreshExecutor) CountTokens(ctx context.Context, a *coreauth.Auth, r execution.Request, o execution.Options) (execution.Response, error) {
	return e.requestExecutor(ctx).CountTokens(ctx, a, r, o)
}

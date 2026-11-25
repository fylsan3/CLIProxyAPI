//go:build cpa_offline

package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"errors"
	"fmt"
	"golang.org/x/net/proxy"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"github.com/MoeForge/moego/json"
	claudeauth "github.com/router-for-me/CLIProxyAPI/v8/internal/auth/claude"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/config"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/registry"
	native "github.com/router-for-me/CLIProxyAPI/v8/internal/runtime/executor"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/runtime/executor/helps"
	_ "github.com/router-for-me/CLIProxyAPI/v8/internal/translator"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/util"
	_ "github.com/router-for-me/CLIProxyAPI/v8/sdk/auth"
	coreauth "github.com/router-for-me/CLIProxyAPI/v8/sdk/cliproxy/auth"
	execution "github.com/router-for-me/CLIProxyAPI/v8/sdk/cliproxy/executor"
	translator "github.com/router-for-me/CLIProxyAPI/v8/sdk/translator"
	log "github.com/sirupsen/logrus"
)

const workerSocket = "/tmp/native-worker.sock"
const originSocket = "/tmp/native-origin.sock"
const authFile = "/state/native-auth.json"

type offlineTraceKey struct{}
type offlineTrace struct{ Run, Attempt string }

type tokenRecord struct {
	Auth         *coreauth.Auth             `json:"auth,omitempty"`
	Renewal      *renewalState              `json:"renewal,omitempty"`
	RefreshIssue string                     `json:"refresh_issue,omitempty"`
	NextRefresh  time.Time                  `json:"next_refresh,omitempty"`
	Owner        string                     `json:"owner"`
	Revision     int                        `json:"revision"`
	Token        claudeauth.ClaudeTokenData `json:"token"`
}
type pendingAuth struct {
	State      string
	PKCE       *claudeauth.PKCECodes
	Expires    time.Time
	Callback   *claudeauth.OAuthServer
	Exchanging bool
	Cancel     context.CancelFunc
}
type worker struct {
	owner              string
	authorizationIssue string
	mu                 sync.Mutex
	record             *tokenRecord
	pending            *pendingAuth
	service            *claudeauth.ClaudeAuth
	executor           *native.ClaudeExecutor
	transport          *providerTransport
	storageFailed      bool
	activeCalls        atomic.Int64
	renewing           atomic.Bool
	manager            *coreauth.Manager
	store              *accountStore
	persist            func(*tokenRecord) error
	renew              func(context.Context, string) (*claudeauth.ClaudeTokenData, error)
}

// Test requests use a local SOCKS adapter; the kernel only allows the bound mock proxy.
type providerTransport struct {
	base     *http.Transport
	owner    string
	provider string
}

func (t *providerTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	allowed := (req.URL.Host == "platform.claude.com" && req.URL.Path == "/v1/oauth/token") ||
		(req.URL.Host == "api.anthropic.com" && (req.URL.Path == "/api/oauth/profile" || req.URL.Path == "/api/oauth/claude_cli/roles" || req.URL.Path == "/v1/messages" || req.URL.Path == "/v1/messages/count_tokens"))
	if !allowed || req.URL.Scheme != "https" || req.URL.User != nil {
		return nil, errors.New("offline_destination_denied")
	}
	if t.provider == "claude-subscription" {
		copy := req.Clone(req.Context())
		applyProviderHeaders(copy)
		return t.send(copy, req)
	}
	if t.provider != "mock-claude" {
		return nil, errors.New("provider_unavailable")
	}
	copy := req.Clone(req.Context())
	// Keep local fixtures on the same identity policy as the provider path.
	applyProviderHeaders(copy)
	target := *req.URL
	target.Scheme = "http"
	target.Host = strings.ToLower(t.owner) + ".upstream.invalid:8080"
	copy.URL = &target
	copy.Host = target.Host
	copy.Header.Set("X-Offline-Owner", t.owner)
	if trace, ok := req.Context().Value(offlineTraceKey{}).(offlineTrace); ok {
		copy.Header.Set("X-Offline-Run", trace.Run)
		copy.Header.Set("X-Offline-Attempt", trace.Attempt)
	}
	return t.send(copy, req)
}

// Apply the explicitly requested model-request header profile at the transport boundary.
// These fixed declarations do not describe the Go runtime. Keep OAuth control headers separate.
func applyProviderHeaders(r *http.Request) {
	if r.URL.Path != "/v1/messages" && r.URL.Path != "/v1/messages/count_tokens" {
		if r.URL.Path == "/v1/oauth/token" || r.URL.Path == "/api/oauth/profile" || r.URL.Path == "/api/oauth/claude_cli/roles" {
			for name := range r.Header {
				if strings.EqualFold(name, "User-Agent") {
					delete(r.Header, name)
				}
			}
			r.Header.Set("User-Agent", "CLIProxyAPI/8.1.1 cpa-container-worker/control-recovery1")
		}
		return
	}
	values := map[string]string{
		"user-agent":                                "claude-cli/2.1.331 (external, sdk-cli)",
		"x-stainless-os":                            "Linux",
		"x-stainless-arch":                          "arm64",
		"x-stainless-runtime":                       "node",
		"x-stainless-runtime-version":               "v26.12.1",
		"x-stainless-lang":                          "js",
		"x-stainless-package-version":               "0.128.0",
		"x-app":                                     "cli",
		"anthropic-dangerous-direct-browser-access": "true",
		"anthropic-version":                         "2023-06-01",
		"accept":                                    "application/json",
		"accept-encoding":                           "gzip, deflate, br, zstd",
	}
	for name := range r.Header {
		lower := strings.ToLower(name)
		_, replace := values[lower]
		if replace {
			delete(r.Header, name)
		}
	}
	for name, value := range values {
		r.Header.Set(name, value)
	}
}

type providerHeadersKey struct{}
type providerHeaderCapture struct {
	mu      sync.Mutex
	headers http.Header
}

func (p *providerHeaderCapture) get() http.Header {
	p.mu.Lock()
	defer p.mu.Unlock()
	return p.headers.Clone()
}
func (t *providerTransport) send(request, source *http.Request) (*http.Response, error) {
	res, err := t.base.RoundTrip(request)
	if res != nil && (source.URL.Path == "/v1/messages" || source.URL.Path == "/v1/messages/count_tokens") {
		if capture, ok := source.Context().Value(providerHeadersKey{}).(*providerHeaderCapture); ok {
			capture.mu.Lock()
			capture.headers = util.ContainerResponseHeaders(res.Header)
			capture.mu.Unlock()
		}
	}
	return res, err
}
func newTransport(owner string) *providerTransport {
	dialer, err := proxy.SOCKS5("tcp", "127.0.0.1:1080", nil, &net.Dialer{})

	return &providerTransport{owner: owner, provider: os.Getenv("CPA_PROVIDER"), base: &http.Transport{MaxIdleConnsPerHost: -1, DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
		if err != nil {
			return nil, err
		}
		contextDialer, ok := dialer.(proxy.ContextDialer)
		if !ok {
			return nil, errors.New("proxy_context_required")
		}
		return contextDialer.DialContext(ctx, network, address)
	}}}
}
func networkCheck() error {
	info, err := os.Lstat("/run/network/firewall.json")
	if err != nil {
		return errors.New("network_firewall_unverified")
	}
	st, ok := info.Sys().(*syscall.Stat_t)
	if !ok || st.Uid != 0 || !info.Mode().IsRegular() || info.Mode().Perm()&0022 != 0 {
		return errors.New("network_firewall_unverified")
	}
	proofRaw, err := os.ReadFile("/run/network/firewall.json")
	if err != nil {
		return err
	}
	var proof struct {
		Config string `json:"config_sha256"`
	}
	if json.Unmarshal(proofRaw, &proof) != nil || proof.Config != os.Getenv("PROXY_CONFIG_SHA256") {
		return errors.New("network_binding_mismatch")
	}
	raw, err := os.ReadFile("/run/network/live/status.json")
	if err != nil {
		return errors.New("account_proxy_unavailable")
	}
	var status struct {
		Healthy bool    `json:"healthy"`
		Checked float64 `json:"checked_at"`
		Owner   string  `json:"owner"`
	}
	if json.Unmarshal(raw, &status) != nil {
		return errors.New("account_proxy_unavailable")
	}
	age := float64(time.Now().UnixNano())/1e9 - status.Checked
	if !status.Healthy || status.Owner != os.Getenv("FIXTURE_OWNER") || age < 0 || age >= 2 {
		return errors.New("account_proxy_unavailable")
	}
	return nil
}
func validToken(owner string, t claudeauth.ClaudeTokenData) bool {
	if os.Getenv("CPA_PROVIDER") == "claude-subscription" {
		return strings.TrimSpace(t.AccessToken) != "" && strings.TrimSpace(t.RefreshToken) != ""
	}
	return strings.HasPrefix(t.AccessToken, "sk-ant-oat01-offline-"+owner+"-") && strings.HasPrefix(t.RefreshToken, "offline-refresh-"+owner+"-")
}
func safeFile(path string) error {
	info, err := os.Lstat(path)
	if err != nil {
		return err
	}
	st, ok := info.Sys().(*syscall.Stat_t)
	if !info.Mode().IsRegular() || !ok || st.Uid != uint32(os.Getuid()) || st.Nlink != 1 || info.Mode().Perm()&0077 != 0 {
		return errors.New("private_file_required")
	}
	return nil
}
func durableWrite(path string, raw []byte) error {
	if err := safeFile(path); err != nil && !os.IsNotExist(err) {
		return err
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".credential-")
	if err != nil {
		return err
	}
	name := f.Name()
	defer os.Remove(name)
	if _, err = f.Write(raw); err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	if err = os.Rename(name, path); err != nil {
		return err
	}
	dir, err := os.Open(filepath.Dir(path))
	if err != nil {
		return err
	}
	defer dir.Close()
	return dir.Sync()
}
func saveRecord(record *tokenRecord) error {
	raw, err := json.Marshal(record)
	if err != nil {
		return err
	}
	if err = durableWrite(authFile, raw); err != nil {
		return err
	}
	// The original CPA save-error semantics remain in accountStore and Manager.
	// An independent committed checkpoint is written only after the account file.
	backup := os.Getenv("CPA_CREDENTIAL_BACKUP")
	if backup == "" {
		return nil
	}
	if backup != "/backup/credentials/latest.json" || os.Getenv("ENVIRONMENT_ID") == "" {
		return errors.New("credential_backup_configuration_invalid")
	}
	checkpoint := struct {
		EnvironmentID string       `json:"environment_id"`
		Record        *tokenRecord `json:"record"`
	}{os.Getenv("ENVIRONMENT_ID"), record}
	encoded, err := json.Marshal(checkpoint)
	if err != nil {
		return err
	}
	return durableWrite(backup, encoded)
}
func (w *worker) load() error {
	if err := networkCheck(); err != nil {
		return err
	}
	if err := safeFile(authFile); os.IsNotExist(err) {
		return nil
	} else if err != nil {
		return err
	}
	raw, err := os.ReadFile(authFile)
	if err != nil {
		return err
	}
	var record tokenRecord
	if json.Unmarshal(raw, &record) != nil || record.Owner != w.owner || !validToken(w.owner, record.Token) {
		return errors.New("offline_credential_required")
	}
	if record.RefreshIssue == "refresh_in_progress" {
		record.RefreshIssue = "refresh_outcome_unknown"
	}
	w.record = &record
	return nil
}
func response(out http.ResponseWriter, status int, value any) {
	out.Header().Set("Content-Type", "application/json")
	out.WriteHeader(status)
	_ = json.NewEncoder(out).Encode(value)
}
func localError(out http.ResponseWriter, status int, code string) {
	response(out, status, map[string]any{"error": map[string]string{"type": "api_error", "message": code}})
}
func (w *worker) status() map[string]any {
	data := map[string]any{"authorization_issue": w.authorizationIssue, "owner": w.owner, "container": os.Getenv("HOSTNAME"), "authorized": false, "revision": 0, "active_calls": w.activeCalls.Load(), "authorization_pending": w.pending != nil && time.Now().Before(w.pending.Expires), "offline_only": os.Getenv("CPA_PROVIDER") != "claude-subscription", "refreshing": w.renewing.Load(), "storage_failed": w.storageFailed, "storage_warning": w.store.failed.Load()}
	auth, ok := w.manager.GetByID(w.authID())
	if !ok {
		data["dispatch_issue"] = "authorization_required"
		return data
	}
	// Read the native passive snapshot; never recompute quota or scheduling state.
	quota := map[string]any{"source": "native_cpa_response_headers", "reported": len(auth.Quota.Signals) > 0, "signals": auth.Quota.Signals}
	if !auth.Quota.ObservedAt.IsZero() {
		quota["observed_at"] = auth.Quota.ObservedAt.Format(time.RFC3339Nano)
	}
	data["quota_observation"] = quota
	data["authorized"] = true
	data["revision"] = auth.CredentialVersion
	expiry, valid := auth.AccessTokenExpirationTime()
	data["expiry_valid"] = valid
	data["expired"] = valid && !time.Now().Before(expiry)
	if valid {
		data["expires"] = expiry.Format(time.RFC3339)
	}
	data["refresh_due"] = w.manager.OfflineRefreshDue(auth, time.Now())
	data["requires_sign_in"] = auth.RequiresSignIn
	data["renewal_state"] = auth.RenewalStateAt(time.Now())
	issue := "account_unavailable"
	modelIssues := map[string]string{}
	for _, m := range registry.GetGlobalRegistry().GetModelsForClient(auth.ID) {
		current := coreauth.OfflineDispatchIssue(auth, m.ID, time.Now())
		modelIssues[m.ID] = current
		if current == "" {
			issue = ""
		} else if issue != "" {
			issue = current
		}
	}
	data["dispatch_issue"] = issue
	data["model_dispatch_issues"] = modelIssues
	if !auth.LastRefreshedAt.IsZero() {
		data["last_refresh"] = auth.LastRefreshedAt.Format(time.RFC3339)
	}
	if !auth.NextRefreshAfter.IsZero() {
		data["next_refresh"] = auth.NextRefreshAfter.Format(time.RFC3339)
	}
	if auth.RefreshError != nil {
		data["refresh_issue"] = "refresh_retry_scheduled"
		if auth.RequiresSignIn {
			data["refresh_issue"] = "refresh_sign_in_required"
		}
	}
	return data
}
func (w *worker) authHandler(out http.ResponseWriter, req *http.Request) {
	if req.URL.Path == "/auth/complete" {
		w.completeAuthorization(out, req)
		return
	}
	if req.URL.Path == "/auth/refresh-check" {
		err := w.refresh(req.Context(), false)
		w.mu.Lock()
		defer w.mu.Unlock()
		response(out, 200, map[string]any{"ok": err == nil, "state": w.status()})
		return
	}
	if req.URL.Path == "/auth/refresh" {
		if err := w.refresh(req.Context(), true); err != nil {
			localError(out, 503, err.Error())
			return
		}
		w.mu.Lock()
		defer w.mu.Unlock()
		response(out, 200, w.status())
		return
	}
	w.mu.Lock()
	defer w.mu.Unlock()
	if err := networkCheck(); err != nil {
		localError(out, 503, "account_proxy_unavailable")
		return
	}
	if req.URL.Path == "/health" {
		response(out, 200, w.status())
		return
	}
	if w.storageFailed {
		localError(out, 503, "credential_save_failed")
		return
	}
	switch req.URL.Path {
	case "/health":
		response(out, 200, w.status())
	case "/auth/begin":
		if w.record != nil {
			localError(out, 409, "already_authorized")
			return
		}
		if w.pending != nil && time.Now().Before(w.pending.Expires) {
			localError(out, 409, "authorization_pending")
			return
		}
		pkce, err := claudeauth.GeneratePKCECodes()
		if err != nil {
			localError(out, 500, "pkce_failed")
			return
		}
		state, err := claudeauth.GenerateState()
		if err != nil {
			localError(out, 500, "state_failed")
			return
		}
		authorize, _, err := w.service.GenerateAuthURL(state, pkce)
		if err != nil {
			localError(out, 500, "authorize_failed")
			return
		}
		parsed, err := url.Parse(authorize)
		if err != nil {
			localError(out, 500, "authorize_failed")
			return
		}
		callback, err := claudeauth.NewBoundOAuthServer(54545, state)
		if err != nil {
			localError(out, 500, "callback_setup_failed")
			return
		}
		if err = callback.Start(); err != nil {
			localError(out, 503, "callback_port_unavailable")
			return
		}
		w.authorizationIssue = ""
		w.pending = &pendingAuth{State: state, PKCE: pkce, Expires: time.Now().Add(10 * time.Minute), Callback: callback}
		go w.awaitBrowserCallback(w.pending)
		// Only the explicitly configured mock provider rewrites authorization destinations.
		if os.Getenv("CPA_PROVIDER") == "mock-claude" {
			parsed.Scheme = "http"
			parsed.Host = strings.ToLower(w.owner) + ".upstream.invalid:8080"
			parsed.Path = "/oauth/authorize"
		}
		response(out, 200, map[string]string{"state": state, "authorization_url": parsed.String()})
	case "/auth/cancel":
		if w.pending != nil && w.pending.Cancel != nil {
			w.pending.Cancel()
		}
		if w.pending != nil && w.pending.Callback != nil {
			_ = w.pending.Callback.Stop(context.Background())
		}
		w.pending = nil
		w.authorizationIssue = "authorization_cancelled"
		response(out, 200, w.status())

	default:
		localError(out, 404, "unknown_action")
	}
}

// Exchange outside the state lock so status and cancellation stay responsive.
func (w *worker) completeAuthorization(out http.ResponseWriter, req *http.Request) {
	if err := networkCheck(); err != nil {
		localError(out, 503, "account_proxy_unavailable")
		return
	}
	var input struct {
		Code  string `json:"code"`
		State string `json:"state"`
	}
	if json.NewDecoder(io.LimitReader(req.Body, 4096)).Decode(&input) != nil {
		localError(out, 400, "invalid_callback")
		return
	}
	w.mu.Lock()
	if w.storageFailed {
		w.mu.Unlock()
		localError(out, 503, "credential_save_failed")
		return
	}
	pending := w.pending
	if pending == nil || time.Now().After(pending.Expires) || subtle.ConstantTimeCompare([]byte(input.State), []byte(pending.State)) != 1 || (os.Getenv("CPA_PROVIDER") == "mock-claude" && input.Code != "offline-code-"+w.owner) || input.Code == "" {
		w.mu.Unlock()
		localError(out, 400, "callback_rejected")
		return
	}
	if pending.Exchanging {
		w.mu.Unlock()
		localError(out, 409, "authorization_exchange_pending")
		return
	}
	ctx, cancel := context.WithCancel(req.Context())
	pending.Exchanging, pending.Cancel = true, cancel
	w.mu.Unlock()
	defer cancel()
	bundle, err := w.service.ExchangeCodeForTokens(ctx, input.Code, pending.State, pending.PKCE)
	w.mu.Lock()
	defer w.mu.Unlock()
	// Cancellation, expiry or replacement must never allow a stale exchange to commit.
	if w.pending != pending || ctx.Err() != nil || time.Now().After(pending.Expires) {
		if w.pending == pending {
			w.pending = nil
			w.authorizationIssue = "authorization_exchange_cancelled"
		}
		localError(out, 409, "authorization_no_longer_active")
		return
	}
	w.pending = nil
	if err != nil {
		w.authorizationIssue = "authorization_exchange_failed"
		localError(out, 502, "offline_token_exchange_failed")
		return
	}
	if !validToken(w.owner, bundle.TokenData) {
		localError(out, 502, "offline_credential_required")
		return
	}
	record := &tokenRecord{Owner: w.owner, Revision: 1, Token: bundle.TokenData}
	if err = saveRecord(record); err != nil {
		w.storageFailed = true
		localError(out, 503, "credential_save_failed")
		return
	}
	w.record = record
	if err = w.register(record); err != nil {
		localError(out, 503, "credential_register_failed")
		return
	}
	w.authorizationIssue = ""
	response(out, 200, w.status())
}

// Authorization code and PKCE remain inside the account container.
func (w *worker) awaitBrowserCallback(pending *pendingAuth) {
	defer func() { _ = pending.Callback.Stop(context.Background()) }()
	for {
		w.mu.Lock()
		current := w.pending == pending
		expired := time.Now().After(pending.Expires)
		if current && expired {
			w.pending = nil
			w.authorizationIssue = "authorization_expired"
		}
		w.mu.Unlock()
		if !current || expired {
			return
		}
		result, err := pending.Callback.WaitForCallback(500 * time.Millisecond)
		if err != nil {
			continue
		}
		if result.Error != "" {
			w.mu.Lock()
			if w.pending == pending {
				w.pending = nil
				w.authorizationIssue = "authorization_denied"
			}
			w.mu.Unlock()
			return
		}
		raw, _ := json.Marshal(map[string]string{"code": result.Code, "state": result.State})
		transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
			return (&net.Dialer{}).DialContext(ctx, "unix", workerSocket)
		}}
		defer transport.CloseIdleConnections()
		client := &http.Client{Transport: transport, Timeout: 35 * time.Second}
		response, err := client.Post("http://worker/auth/complete", "application/json", bytes.NewReader(raw))
		ok := err == nil && response.StatusCode == 200
		if response != nil {
			_, _ = io.Copy(io.Discard, io.LimitReader(response.Body, 65536))
			_ = response.Body.Close()
		}
		if !ok {
			w.mu.Lock()
			if w.record == nil {
				w.authorizationIssue = "authorization_exchange_failed"
				if w.pending == pending {
					w.pending = nil
				}
			}
			w.mu.Unlock()
		}
		return
	}
}

// Refresh scheduling decisions, error classification, and commit semantics remain in CPA.
func (w *worker) refresh(ctx context.Context, force bool) error {
	if err := networkCheck(); err != nil {
		return err
	}
	if _, ok := w.manager.GetByID(w.authID()); !ok {
		return errors.New("authorization_required")
	}
	var err error
	if force {
		_, err = w.manager.ForceRefreshAuth(ctx, w.authID())
	} else {
		err = w.manager.OfflineRefreshIfDue(ctx, w.authID())
	}
	// CPA records refresh failures in memory. Keep an explicit container checkpoint
	// so restarting this isolated worker does not lose the sign-in/backoff state.
	if err != nil {
		w.checkpoint()
	}
	return err
}
func (w *worker) checkpoint() {
	if a, ok := w.manager.GetByID(w.authID()); ok {
		_, _ = w.store.Save(context.Background(), a)
	}
}
func (w *worker) refreshLoop(ctx context.Context) {
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()
	for {
		_ = w.refresh(ctx, false)
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}
	}
}

func nativeError(out http.ResponseWriter, err error, observed ...http.Header) {
	var headers http.Header
	if len(observed) > 0 {
		headers = observed[0]
	}
	status := 502
	var code interface{ StatusCode() int }
	if errors.As(err, &code) {
		status = code.StatusCode()
	}
	var raw interface{ ClaudeResponseBody() (string, bool) }
	if errors.As(err, &raw) {
		if body, ok := raw.ClaudeResponseBody(); ok {
			copyHeaders(out, headers)
			if out.Header().Get("Content-Type") == "" {
				out.Header().Set("Content-Type", "application/json")
			}
			out.WriteHeader(status)
			_, _ = out.Write([]byte(body))
			return
		}
	}
	var body interface{ ResponseBody() []byte }
	if errors.As(err, &body) {
		copyHeaders(out, headers)
		if out.Header().Get("Content-Type") == "" {
			out.Header().Set("Content-Type", "application/json")
		}
		out.WriteHeader(status)
		_, _ = out.Write(body.ResponseBody())
		return
	}
	if len(headers) > 0 {
		localError(out, 502, "upstream_response_unreadable")
		return
	}
	localError(out, status, "native_execution_failed")
}
func copyHeaders(out http.ResponseWriter, headers http.Header) {
	for name, values := range util.ContainerResponseHeaders(headers) {
		out.Header()[name] = append([]string(nil), values...)
	}
}

// Each request keeps its own auth snapshot; refresh does not gate model calls.
func (w *worker) beginCall(ctx context.Context, model string) (*coreauth.Auth, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	auth, ok := w.manager.GetByID(w.authID())
	if !ok {
		return nil, errors.New("authorization_required")
	}
	if issue := coreauth.OfflineDispatchIssue(auth, model, time.Now()); issue != "" {
		return nil, errors.New(issue)
	}
	w.activeCalls.Add(1)
	return auth, nil
}

// Decode routing fields without rebuilding or filtering the caller's payload.
func messageRequest(raw []byte, headers http.Header) (execution.Request, execution.Options, error) {
	var params struct {
		Model  string `json:"model"`
		Stream bool   `json:"stream"`
	}
	trimmed := bytes.TrimSpace(raw)
	if len(trimmed) == 0 || trimmed[0] != '{' || json.Unmarshal(raw, &params) != nil || strings.TrimSpace(params.Model) == "" {
		return execution.Request{}, execution.Options{}, errors.New("invalid_message_request")
	}
	format := translator.FromString("claude")
	return execution.Request{Model: params.Model, Payload: raw, Format: format}, execution.Options{
		Headers: util.ContainerRequestHeaders(headers), Stream: params.Stream,
		SourceFormat: format, ResponseFormat: format, OriginalRequest: raw,
	}, nil
}

func (w *worker) messages(out http.ResponseWriter, req *http.Request) {
	if err := networkCheck(); err != nil {
		localError(out, 503, "account_proxy_unavailable")
		return
	}
	raw, err := io.ReadAll(req.Body)
	if err != nil {
		localError(out, 400, "invalid_request")
		return
	}
	cfg, configErr := util.DecodeContainerConfig(req.Header.Get(util.ContainerConfigHeader))
	if configErr != nil {
		localError(out, 400, configErr.Error())
		return
	}
	request, options, err := messageRequest(raw, req.Header)
	if err != nil {
		localError(out, 400, "invalid_request")
		return
	}
	_, err = w.beginCall(req.Context(), request.Model)
	if err != nil {
		if errors.Is(err, context.Canceled) {
			return
		}
		localError(out, 503, err.Error())
		return
	}
	defer w.activeCalls.Add(-1)
	defer w.checkpoint()
	capture := &providerHeaderCapture{}
	ctx := coreauth.WithRequestScopedErrorConfig(helps.WithContainerResponseMode(req.Context()), cfg)
	ctx = context.WithValue(ctx, providerHeadersKey{}, capture)
	w.manager.SetConfig(cfg)
	ctx = context.WithValue(ctx, "cliproxy.roundtripper", http.RoundTripper(w.transport))
	ctx = context.WithValue(ctx, offlineTraceKey{}, offlineTrace{Run: req.Header.Get("X-Offline-Run"), Attempt: req.Header.Get("X-Offline-Attempt")})
	out.Header().Set("X-Offline-Container", os.Getenv("HOSTNAME"))
	out.Header().Set("X-Offline-Owner", w.owner)
	if req.URL.Path == "/v1/messages/count_tokens" {
		options.Stream = false
		result, err := w.manager.ExecuteCount(ctx, []string{"claude"}, request, options)
		if err != nil {
			nativeError(out, err, capture.get())
			return
		}
		copyHeaders(out, result.Headers)
		out.Header().Set("Content-Type", "application/json")
		out.WriteHeader(200)
		_, _ = out.Write(result.Payload)
		return
	}
	if options.Stream {
		stream, err := w.manager.ExecuteStream(ctx, []string{"claude"}, request, options)
		if err != nil {
			nativeError(out, err, capture.get())
			return
		}
		copyHeaders(out, stream.Headers)
		out.Header().Set("Content-Type", "text/event-stream")
		out.WriteHeader(200)
		errorDelivered := false
		for chunk := range stream.Chunks {
			if chunk.Err != nil {
				if errorDelivered {
					return
				}
				panic(http.ErrAbortHandler)
			}
			if completeSSEError(chunk.Payload) {
				errorDelivered = true
			}
			if _, err = out.Write(chunk.Payload); err != nil {
				return
			}
			if flush, ok := out.(http.Flusher); ok {
				flush.Flush()
			}
		}
		if ctx.Err() != nil {
			panic(http.ErrAbortHandler)
		}
		return
	}
	result, err := w.manager.Execute(ctx, []string{"claude"}, request, options)
	if err != nil {
		nativeError(out, err, capture.get())
		return
	}
	copyHeaders(out, result.Headers)
	out.Header().Set("Content-Type", "application/json")
	out.WriteHeader(200)
	_, _ = out.Write(result.Payload)
}

// Owner syntax is shared with the control registry; account existence is bound by the mounted network configuration.
func validAccountOwner(owner string) bool {
	if len(owner) < 1 || len(owner) > 32 || owner[0] < 'A' || owner[0] > 'Z' || owner[len(owner)-1] == '-' {
		return false
	}
	for _, c := range owner {
		if !(c >= 'A' && c <= 'Z' || c >= '0' && c <= '9' || c == '-') {
			return false
		}
	}
	return true
}
func serve() error {
	owner := os.Getenv("FIXTURE_OWNER")
	if !validAccountOwner(owner) {
		return errors.New("offline_owner_required")
	}
	if err := networkCheck(); err != nil {
		return err
	}
	if info, err := os.Lstat("/state"); err != nil || !info.IsDir() || info.Mode()&os.ModeSymlink != 0 {
		return errors.New("state_directory_required")
	}
	lock, err := os.OpenFile("/state/native.lock", os.O_CREATE|os.O_RDWR|syscall.O_NOFOLLOW, 0600)
	if err != nil {
		return err
	}
	defer lock.Close()
	if err = syscall.Flock(int(lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		return err
	}
	provider := os.Getenv("CPA_PROVIDER")
	if provider != "mock-claude" && provider != "claude-subscription" {
		return errors.New("provider_unavailable")
	}
	transport := newTransport(owner)
	client := &http.Client{Transport: transport, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	service := claudeauth.NewOfflineAuth(client)
	if provider == "claude-subscription" {
		service = claudeauth.NewContainerAuth(client)
	}
	w := &worker{owner: owner, transport: transport, service: service, executor: native.NewClaudeExecutor(&config.Config{DisableClaudeCloakMode: true})}
	if err = w.load(); err != nil {
		return err
	}
	if err = w.setup(); err != nil {
		return err
	}
	lifecycle, stopRefresh := context.WithCancel(context.Background())
	defer stopRefresh()
	if os.Getenv("OFFLINE_CENTRAL_REFRESH") != "1" {
		return errors.New("central_refresh_scheduler_required")
	}
	_ = lifecycle
	if err = os.Remove(workerSocket); err != nil && !os.IsNotExist(err) {
		return err
	}
	listener, err := net.Listen("unix", workerSocket)
	if err != nil {
		return err
	}
	defer listener.Close()
	if err = os.Chmod(workerSocket, 0600); err != nil {
		return err
	}
	mux := http.NewServeMux()
	mux.HandleFunc("/v1/messages", w.messages)
	mux.HandleFunc("/v1/messages/count_tokens", w.messages)
	mux.HandleFunc("/", w.authHandler)
	server := &http.Server{Handler: mux, MaxHeaderBytes: 8192}
	return server.Serve(listener)
}

// call is the fixed-command broker bridge. It never reads or returns credential files.
func call() error {
	var input struct {
		Path            string          `json:"path"`
		Body            json.RawMessage `json:"body"`
		Run             string          `json:"run"`
		Attempt         string          `json:"attempt"`
		WatchInput      bool            `json:"watch_input"`
		Headers         http.Header     `json:"headers"`
		ExecutionConfig string          `json:"execution_config"`
	}
	if err := json.NewDecoder(os.Stdin).Decode(&input); err != nil {
		return err
	}
	switch input.Path {
	case "/health", "/auth/refresh-check", "/auth/begin", "/auth/complete", "/auth/cancel", "/auth/refresh", "/v1/messages", "/v1/messages/count_tokens":
	default:
		return errors.New("unknown_action")
	}
	transport := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{Timeout: time.Second}).DialContext(ctx, "unix", workerSocket)
	}}
	defer transport.CloseIdleConnections()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	// The broker keeps stdin open for model calls. EOF propagates caller cancellation
	// even while the provider has not sent response headers or another stream chunk.
	if input.WatchInput && (strings.HasPrefix(input.Path, "/v1/messages") || strings.HasPrefix(input.Path, "/auth/")) {
		go func() {
			_, _ = io.Copy(io.Discard, os.Stdin)
			cancel()
		}()
	}
	request, err := http.NewRequestWithContext(ctx, "POST", "http://worker"+input.Path, bytes.NewReader(input.Body))
	if err != nil {
		return err
	}
	request.Header = util.ContainerRequestHeaders(input.Headers)
	if input.ExecutionConfig != "" {
		if _, err := util.DecodeContainerConfig(input.ExecutionConfig); err != nil {
			return err
		}
		request.Header.Set(util.ContainerConfigHeader, input.ExecutionConfig)
	}
	request.Header.Set("X-Offline-Run", input.Run)
	request.Header.Set("X-Offline-Attempt", input.Attempt)
	inputHash := sha256.Sum256(input.Body)
	result, err := transport.RoundTrip(request)
	if err != nil {
		return err
	}
	defer result.Body.Close()
	encoder := json.NewEncoder(os.Stdout)
	if err = encoder.Encode(map[string]any{"status": result.StatusCode, "headers": result.Header}); err != nil {
		return err
	}
	hash := sha256.New()
	buffer := make([]byte, 8192)
	for {
		n, readErr := result.Body.Read(buffer)
		if n > 0 {
			hash.Write(buffer[:n])
			if err = encoder.Encode(map[string]any{"body": buffer[:n]}); err != nil {
				return err
			}
		}
		if readErr == io.EOF {
			break
		}
		if readErr != nil {
			return readErr
		}
	}
	return encoder.Encode(map[string]any{"done": true, "owner": os.Getenv("FIXTURE_OWNER"), "container": os.Getenv("HOSTNAME"), "run": input.Run, "attempt": input.Attempt, "response_sha256": hex.EncodeToString(hash.Sum(nil)), "input_sha256": hex.EncodeToString(inputHash[:])})
}
func main() {
	log.SetOutput(io.Discard)
	var err error
	if len(os.Args) == 2 && os.Args[1] == "call" {
		err = call()
	} else if len(os.Args) == 2 && os.Args[1] == "serve" {
		err = serve()
	} else {
		err = errors.New("expected serve or call")
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "offline_worker_failed")
		os.Exit(1)
	}
}

// Native Claude chunks contain complete events. Only a complete upstream error
// permits a normal HTTP end; a network truncation still aborts the connection.
func completeSSEError(payload []byte) bool {
	normalized := bytes.ReplaceAll(payload, []byte("\r\n"), []byte("\n"))
	if !bytes.HasSuffix(normalized, []byte("\n\n")) {
		return false
	}
	for _, event := range bytes.Split(normalized, []byte("\n\n")) {
		var data []byte
		for _, line := range bytes.Split(event, []byte("\n")) {
			if bytes.HasPrefix(line, []byte("data:")) {
				if len(data) > 0 {
					data = append(data, '\n')
				}
				data = append(data, bytes.TrimPrefix(bytes.TrimPrefix(line, []byte("data:")), []byte(" "))...)
			}
		}
		var value struct {
			Type string `json:"type"`
		}
		if json.Unmarshal(data, &value) == nil && value.Type == "error" {
			return true
		}
	}
	return false
}

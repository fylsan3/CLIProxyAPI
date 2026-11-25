package management

import (
	"bufio"
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"net"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/MoeForge/moego/json"
	"github.com/MoeForge/moego/ojson"
	"github.com/gin-gonic/gin"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/config"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/registry"
	native "github.com/router-for-me/CLIProxyAPI/v8/internal/runtime/executor"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/runtime/executor/helps"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/thinking"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/util"
	coreauth "github.com/router-for-me/CLIProxyAPI/v8/sdk/cliproxy/auth"
	execution "github.com/router-for-me/CLIProxyAPI/v8/sdk/cliproxy/executor"
)

func validProjectSlug(slug string) bool {
	if len(slug) < 1 || len(slug) > 32 || slug[0] < 'a' || slug[0] > 'z' || slug[len(slug)-1] == '-' {
		return false
	}
	for _, c := range slug {
		if !(c >= 'a' && c <= 'z' || c >= '0' && c <= '9' || c == '-') {
			return false
		}
	}
	return true
}

const projectPoolModel = "test-project-shared"
const projectProvider = "isolated-project-fixture"

type projectRequestKey struct{}
type projectCountKey struct{}
type projectPool struct {
	manager        *coreauth.Manager
	renewal        *coreauth.Manager
	refreshWorkers int
	executor       *projectExecutor
	mu             sync.Mutex
}
type projectExecutor struct {
	socket    string
	namespace string
	transport *http.Transport
}
type projectHTTPError struct {
	status  int
	body    []byte
	headers http.Header
}

func (e *projectHTTPError) Headers() http.Header { return e.headers.Clone() }
func (e *projectHTTPError) Error() string        { return "isolated project request failed" }
func (e *projectHTTPError) StatusCode() int      { return e.status }

var projectPools sync.Map

func (h *Handler) isolatedProjectPool() *projectPool {
	if value, ok := projectPools.Load(h); ok {
		return value.(*projectPool)
	}
	h.mu.Lock()
	defer h.mu.Unlock()
	if value, ok := projectPools.Load(h); ok {
		return value.(*projectPool)
	}
	cfg := &config.Config{}
	if h.cfg != nil {
		cfg.Routing = h.cfg.Routing
		cfg.DisableCooling = h.cfg.DisableCooling
		cfg.TransientErrorCooldownSeconds = h.cfg.TransientErrorCooldownSeconds
		cfg.AuthAutoRefreshWorkers = h.cfg.AuthAutoRefreshWorkers
		cfg.RequestRetry = h.cfg.RequestRetry
		cfg.MaxRetryCredentials = h.cfg.MaxRetryCredentials
		cfg.MaxRetryInterval = h.cfg.MaxRetryInterval
	}
	var selector coreauth.Selector = &coreauth.RoundRobinSelector{}
	switch cfg.Routing.Strategy {
	case "fill-first":
		selector = &coreauth.FillFirstSelector{}
	case "weighted-round-robin":
		selector = &coreauth.WeightedRoundRobinSelector{}
	}
	if cfg.Routing.SessionAffinity {
		ttl, err := time.ParseDuration(cfg.Routing.SessionAffinityTTL)
		if err != nil || ttl <= 0 {
			ttl = time.Hour
		}
		if ttl < time.Second {
			ttl = time.Second
		}
		selector = coreauth.NewSessionAffinitySelectorWithConfig(coreauth.SessionAffinityConfig{
			Fallback: selector, TTL: ttl, SubagentAffinity: cfg.Routing.SessionAffinitySubagents,
			RebindOn: cfg.Routing.SessionAffinityRebindOn,
		})
	}
	socket := h.containerControlSocket()
	sum := sha256.Sum256([]byte(socket))
	executor := &projectExecutor{socket: socket, namespace: "local-fixture-" + hex.EncodeToString(sum[:8]) + "-"}
	executor.transport = &http.Transport{DisableKeepAlives: true, DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{Timeout: time.Second}).DialContext(ctx, "unix", socket)
	}}
	manager := coreauth.NewManager(nil, selector, nil)
	manager.SetConfig(cfg)
	manager.SetRetryConfig(cfg.RequestRetry, time.Duration(cfg.MaxRetryInterval)*time.Second, cfg.MaxRetryCredentials)
	manager.RegisterExecutor(executor)
	pool := &projectPool{manager: manager, executor: executor}
	pool.initRenewal(cfg)
	projectPools.Store(h, pool)
	return pool
}

func (p *projectPool) registerFixtures(ctx context.Context) error {
	p.mu.Lock()
	defer p.mu.Unlock()
	req, err := http.NewRequestWithContext(ctx, "POST", "http://local/admin/list", strings.NewReader("{}"))
	if err != nil {
		return err
	}
	res, err := p.executor.transport.RoundTrip(req)
	if err != nil {
		return err
	}
	defer res.Body.Close()
	if res.StatusCode != 200 {
		return errors.New("fixture registry unavailable")
	}
	var list struct {
		Projects []struct {
			Slug   string
			Models []string
			State  projectRemoteState
		}
	}
	if err = json.NewDecoder(io.LimitReader(res.Body, 262144)).Decode(&list); err != nil {
		return err
	}
	// The private control registry supplies identities and provider model bindings.
	for _, project := range list.Projects {
		if !validProjectSlug(project.Slug) {
			continue
		}
		if err = p.observeRenewal(ctx, project.Slug, project.State); err != nil {
			return err
		}
		id := p.executor.namespace + project.Slug
		if _, ok := p.manager.GetByID(id); ok {
			continue
		}
		models := []*registry.ModelInfo{}
		for _, model := range project.Models {
			if model == projectPoolModel {
				models = append(models, &registry.ModelInfo{ID: model})
				continue
			}
			for _, nativeModel := range registry.GetClaudeModels() {
				if nativeModel.ID == model {
					models = append(models, nativeModel)
					break
				}
			}
		}
		if len(models) == 0 {
			continue
		}
		registry.GetGlobalRegistry().RegisterClient(id, projectProvider, models)
		if _, err = p.manager.Register(ctx, &coreauth.Auth{ID: id, Provider: projectProvider, Status: coreauth.StatusActive, Attributes: map[string]string{"dispatch_model": models[0].ID}}); err != nil {
			registry.GetGlobalRegistry().UnregisterClient(id)
			return err
		}
	}
	return nil
}
func (e *projectExecutor) Identifier() string { return projectProvider }
func (e *projectExecutor) request(ctx context.Context, a *coreauth.Auth, r execution.Request, opts execution.Options) (*http.Response, error) {
	slug := strings.TrimPrefix(a.ID, e.namespace)
	if a.Provider != projectProvider || !strings.HasPrefix(a.ID, e.namespace) || !validProjectSlug(slug) {
		return nil, &coreauth.Error{Code: coreauth.ErrorCodeRequestScoped, HTTPStatus: 400, Message: "invalid fixture"}
	}
	path := "/v1/messages"
	if count, _ := ctx.Value(projectCountKey{}).(bool); count {
		path += "/count_tokens"
	}
	req, err := http.NewRequestWithContext(ctx, "POST", "http://local"+path, bytes.NewReader(r.Payload))
	if err != nil {
		return nil, err
	}
	req.Header = util.ContainerRequestHeaders(opts.Headers)
	if setting, ok := opts.Metadata["container_execution_config"].(string); ok {
		req.Header.Set(util.ContainerConfigHeader, setting)
	}
	run, _ := ctx.Value(projectRequestKey{}).(string)
	req.Header.Set("X-Test-Request", run)
	req.Header.Set("X-Test-Project", slug)
	req.Header.Set("X-Test-Model", thinking.ParseSuffix(r.Model).ModelName)
	req.Header.Set("Content-Type", "application/json")
	execution.MarkUpstreamAttempt(ctx)
	res, err := e.transport.RoundTrip(req)
	if err != nil {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		return nil, &coreauth.Error{Code: coreauth.ErrorCodeTransientTransport, HTTPStatus: 503, Retryable: true, Message: "fixture transport unavailable"}
	}
	if res.StatusCode < 200 || res.StatusCode >= 300 {
		defer res.Body.Close()
		body, readErr := io.ReadAll(res.Body)
		if readErr != nil {
			return nil, readErr
		}
		return nil, &projectHTTPError{status: res.StatusCode, body: body, headers: res.Header.Clone()}
	}
	return res, nil
}
func (e *projectExecutor) Execute(ctx context.Context, a *coreauth.Auth, r execution.Request, opts execution.Options) (execution.Response, error) {
	res, err := e.request(ctx, a, r, opts)
	if err != nil {
		return execution.Response{}, err
	}
	defer res.Body.Close()
	body, err := io.ReadAll(res.Body)
	if err != nil {
		return execution.Response{}, err
	}
	return execution.Response{Payload: body, Headers: res.Header}, nil
}
func (e *projectExecutor) ExecuteStream(ctx context.Context, a *coreauth.Auth, r execution.Request, opts execution.Options) (*execution.StreamResult, error) {
	res, err := e.request(ctx, a, r, opts)
	if err != nil {
		return nil, err
	}
	chunks := make(chan execution.StreamChunk)
	go func() {
		defer close(chunks)
		defer res.Body.Close()

		scanner := bufio.NewScanner(res.Body)
		scanner.Buffer(nil, 52_428_800)
		scanner.Split(helps.ScanSSELineWithEnding)
		var event bytes.Buffer
		for scanner.Scan() {
			line := append([]byte(nil), scanner.Bytes()...)
			select {
			case chunks <- execution.StreamChunk{Payload: line}:
			case <-ctx.Done():
				return
			}
			event.Write(line)
			if len(bytes.TrimSpace(line)) == 0 {
				failure := native.ClaudeContainerStreamError(event.Bytes())
				event.Reset()
				if failure != nil {
					select {
					case chunks <- execution.StreamChunk{Err: failure}:
					case <-ctx.Done():
					}
					return
				}
			}
		}
		if err := scanner.Err(); err != nil {
			select {
			case chunks <- execution.StreamChunk{Err: err}:
			case <-ctx.Done():
			}
		}

	}()
	return &execution.StreamResult{Headers: res.Header, Chunks: chunks}, nil
}
func (e *projectExecutor) Refresh(_ context.Context, a *coreauth.Auth) (*coreauth.Auth, error) {
	return a, nil
}
func (e *projectExecutor) CountTokens(ctx context.Context, a *coreauth.Auth, r execution.Request, opts execution.Options) (execution.Response, error) {
	return e.Execute(context.WithValue(ctx, projectCountKey{}, true), a, r, opts)
}
func (e *projectExecutor) HttpRequest(context.Context, *coreauth.Auth, *http.Request) (*http.Response, error) {
	return nil, errors.New("fixture supports only local Messages requests")
}
func projectCopyHeaders(c *gin.Context, h http.Header) {
	for name, values := range util.ContainerResponseHeaders(h) {
		if c.Writer.Header().Get(name) == "" {
			c.Writer.Header()[name] = append([]string(nil), values...)
		}
	}
	// These are supplied by the private bridge after its receipt checks.
	for _, name := range []string{"X-Test-Container", "X-Test-Attempt", "X-Test-Response-SHA256"} {
		if value := h.Get(name); value != "" {
			c.Header(name, value)
		}
	}
	if c.Writer.Header().Get("Cache-Control") == "" {
		c.Header("Cache-Control", "no-store")
	}
}
func projectWriteError(c *gin.Context, err error) {
	var original *projectHTTPError
	if errors.As(err, &original) {
		projectCopyHeaders(c, original.headers)
		kind := c.Writer.Header().Get("Content-Type")
		if kind == "" {
			kind = "application/json"
		}
		c.Data(original.status, kind, original.body)
		return
	}
	status := 503
	var coded interface{ StatusCode() int }
	if errors.As(err, &coded) && coded.StatusCode() >= 400 {
		status = coded.StatusCode()
	}
	c.JSON(status, gin.H{"error": gin.H{"type": "api_error", "message": "fixture_execution_failed"}})
}
func (h *Handler) projectSharedMessages(c *gin.Context, body []byte, run string, stream bool) {
	pool := h.isolatedProjectPool()
	ctx, cancel := context.WithCancel(context.WithValue(c.Request.Context(), projectRequestKey{}, run))
	defer cancel()
	if err := pool.registerFixtures(ctx); err != nil {
		projectWriteError(c, err)
		return
	}
	h.mu.Lock()
	settings := util.ContainerConfigSnapshot(h.cfg)
	h.mu.Unlock()
	encoded, configErr := util.EncodeContainerConfig(settings)
	if configErr != nil {
		c.JSON(500, gin.H{"error": gin.H{"message": configErr.Error()}})
		return
	}
	opts := execution.Options{Stream: stream, Headers: c.Request.Header.Clone(), OriginalRequest: body, Metadata: map[string]any{"container_execution_config": encoded}}
	if pin := c.GetHeader("X-Test-Pin"); pin != "" {
		_, registered := pool.manager.GetByID(pool.executor.namespace + pin)
		if !validProjectSlug(pin) || !registered {
			c.Status(400)
			return
		}
		opts.Metadata[execution.PinnedAuthMetadataKey] = pool.executor.namespace + pin
	}
	req := execution.Request{Model: ojson.GetBytesNoCopy(body, "model").String(), Payload: body}
	if c.Request.URL.Path == "/v1/messages/count_tokens" {
		opts.Stream = false
		res, err := pool.manager.ExecuteCount(ctx, []string{projectProvider}, req, opts)
		if err != nil {
			projectWriteError(c, err)
			return
		}
		projectCopyHeaders(c, res.Headers)
		c.Data(200, "application/json", res.Payload)
		return
	}
	if !stream {
		res, err := pool.manager.Execute(ctx, []string{projectProvider}, req, opts)
		if err != nil {
			projectWriteError(c, err)
			return
		}
		projectCopyHeaders(c, res.Headers)
		c.Data(200, "application/json", res.Payload)
		return
	}
	res, err := pool.manager.ExecuteStream(ctx, []string{projectProvider}, req, opts)
	if err != nil {
		projectWriteError(c, err)
		return
	}
	projectCopyHeaders(c, res.Headers)
	c.Header("Content-Type", "text/event-stream")
	for chunk := range res.Chunks {
		if chunk.Err != nil {
			var delivered interface{ UpstreamClaudeStreamError() bool }
			if errors.As(chunk.Err, &delivered) && delivered.UpstreamClaudeStreamError() {
				return
			}
			panic(http.ErrAbortHandler)
		}
		if _, err = c.Writer.Write(chunk.Payload); err != nil {
			return
		}
		c.Writer.Flush()
	}
}

// ProjectPoolStatus exposes only synthetic scheduler state, never account metadata.
func (h *Handler) ProjectPoolStatus(c *gin.Context) {
	pool := h.isolatedProjectPool()
	if err := pool.registerFixtures(c.Request.Context()); err != nil {
		c.JSON(503, gin.H{"error": "status_unavailable"})
		return
	}
	rows := []gin.H{}
	for _, a := range pool.manager.List() {
		slug := strings.TrimPrefix(a.ID, pool.executor.namespace)
		views := map[string]any{}
		view := map[string]any{"eligible": false, "reason": "unavailable"}
		for _, model := range registry.GetGlobalRegistry().GetModelsForClient(a.ID) {
			current := coreauth.LocalProjectDispatchView(a, model.ID, time.Now())
			views[model.ID] = current
			if eligible, _ := current["eligible"].(bool); eligible {
				view = map[string]any{}
				for key, value := range current {
					view[key] = value
				}
			}
		}
		view["models"] = views
		rows = append(rows, gin.H{"slug": slug, "dispatch": view})
	}
	c.JSON(200, gin.H{"started": true, "accounts": rows, "refresh_workers": pool.refreshWorkers, "refresh_engine": "CPA StartAutoRefresh / ForceRefreshAll", "single_refresh_and_401_share_global_limit": false})
}

package management

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/MoeForge/moego/json"
	"github.com/gin-gonic/gin"
	baseauth "github.com/router-for-me/CLIProxyAPI/v8/internal/auth"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/config"
	coreauth "github.com/router-for-me/CLIProxyAPI/v8/sdk/cliproxy/auth"
)

const projectRefreshProvider = "isolated-project-renewal"

// Runtime carries only observed scheduling facts. No credential enters the central process.
type projectRefreshRuntime struct {
	mu                          sync.RWMutex
	due, authorized, refreshing bool
	observed                    time.Time
}

func (r *projectRefreshRuntime) set(state projectRemoteState, at time.Time) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.due = state.RefreshDue
	r.authorized = state.Authorized
	r.refreshing = state.Refreshing
	r.observed = at
}
func (r *projectRefreshRuntime) ShouldRefresh(now time.Time, _ *coreauth.Auth) bool {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.authorized && r.due && !r.refreshing && !r.observed.IsZero() && now.Sub(r.observed) < 15*time.Second
}

type projectRemoteState struct {
	Authorized bool `json:"authorized"`
	RefreshDue bool `json:"refresh_due"`
	Refreshing bool `json:"refreshing"`
}
type projectRefreshExecutor struct{ *projectExecutor }

func (e *projectRefreshExecutor) Identifier() string { return projectRefreshProvider }
func (e *projectRefreshExecutor) Refresh(ctx context.Context, a *coreauth.Auth) (*coreauth.Auth, error) {
	slug := strings.TrimPrefix(a.ID, e.namespace)
	if a.Provider != projectRefreshProvider || !strings.HasPrefix(a.ID, e.namespace) || !validProjectSlug(slug) {
		return nil, errors.New("invalid offline renewal account")
	}
	action := "refresh-check"
	if coreauth.IsForceRefreshContext(ctx) {
		action = "refresh-execute"
	}
	body, _ := json.Marshal(map[string]string{"slug": slug})
	req, err := http.NewRequestWithContext(ctx, "POST", "http://local/admin/"+action, bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	resp, err := e.transport.RoundTrip(req)
	if err != nil {
		return nil, errors.New("container renewal transport unavailable")
	}
	defer resp.Body.Close()
	if resp.StatusCode != 200 {
		return nil, errors.New("container renewal bridge unavailable")
	}
	var result struct {
		OK    bool               `json:"ok"`
		State projectRemoteState `json:"state"`
	}
	if err = json.NewDecoder(io.LimitReader(resp.Body, 65536)).Decode(&result); err != nil {
		return nil, errors.New("invalid renewal receipt")
	}
	if runtime, ok := a.Runtime.(*projectRefreshRuntime); ok {
		runtime.set(result.State, time.Now())
	}
	// The container's original CPA manager already classified the token error.
	// Deferred keeps the opaque scheduler from inventing a second credential policy.
	if !result.OK {
		return nil, baseauth.ErrRefreshDeferred
	}
	return a, nil
}
func (p *projectPool) initRenewal(cfg *config.Config) {
	p.renewal = coreauth.NewManager(nil, nil, nil)
	p.renewal.SetConfig(cfg)
	p.renewal.RegisterExecutor(&projectRefreshExecutor{p.executor})
	p.refreshWorkers = p.renewal.LocalProjectRefreshWorkers()
	p.renewal.StartAutoRefresh(context.Background(), 0)
	go func() {
		ticker := time.NewTicker(5 * time.Second)
		defer ticker.Stop()
		for range ticker.C {
			_ = p.registerFixtures(context.Background())
		}
	}()
}
func (p *projectPool) observeRenewal(ctx context.Context, slug string, state projectRemoteState) error {
	id := p.executor.namespace + slug
	if a, ok := p.renewal.GetByID(id); ok {
		if r, ok := a.Runtime.(*projectRefreshRuntime); ok {
			r.set(state, time.Now())
		}
		return nil
	}
	r := &projectRefreshRuntime{}
	r.set(state, time.Now())
	_, err := p.renewal.Register(ctx, &coreauth.Auth{ID: id, Provider: projectRefreshProvider, Status: coreauth.StatusActive, Runtime: r})
	return err
}
func (h *Handler) ProjectRefresh(c *gin.Context) {
	p := h.isolatedProjectPool()
	if err := p.registerFixtures(c.Request.Context()); err != nil {
		c.JSON(503, gin.H{"error": "renewal_registry_unavailable"})
		return
	}
	if c.Param("action") == "refresh-all" {
		results := p.renewal.ForceRefreshAll(c.Request.Context())
		rows := []gin.H{}
		for _, r := range results {
			rows = append(rows, gin.H{"slug": strings.TrimPrefix(r.ID, p.executor.namespace), "success": r.Success})
		}
		c.JSON(200, gin.H{"results": rows})
		return
	}
	var body struct {
		Slug string `json:"slug"`
	}
	if c.ShouldBindJSON(&body) != nil || !validProjectSlug(body.Slug) {
		c.JSON(400, gin.H{"error": "invalid_owner"})
		return
	}
	_, err := p.renewal.ForceRefreshAuth(c.Request.Context(), p.executor.namespace+body.Slug)
	if err != nil {
		c.JSON(503, gin.H{"error": "refresh_not_completed"})
		return
	}
	c.JSON(200, gin.H{"ok": true})
}

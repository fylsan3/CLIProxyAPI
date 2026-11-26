package management

import (
	"bytes"
	"context"
	"encoding/json"
	"github.com/gin-gonic/gin"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/credentialweight"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/registry"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
)

// The original routing UI edits non-secret container metadata; tokens stay in workers.
func (h *Handler) containerMetadata(ctx context.Context, path string, payload any) (int, []byte, error) {
	b, e := json.Marshal(payload)
	if e != nil {
		return 0, nil, e
	}
	req, e := http.NewRequestWithContext(ctx, "POST", "http://local/admin/"+path, bytes.NewReader(b))
	if e != nil {
		return 0, nil, e
	}
	res, e := h.isolatedProjectPool().executor.transport.RoundTrip(req)
	if e != nil {
		return 0, nil, e
	}
	defer res.Body.Close()
	b, e = io.ReadAll(io.LimitReader(res.Body, 2*1024*1024+1))
	if len(b) > 2*1024*1024 {
		return 502, nil, io.ErrUnexpectedEOF
	}
	return res.StatusCode, b, e
}
func (h *Handler) ContainerCredentials(c *gin.Context) {
	if os.Getenv("CPA_CONTAINER_ROUTING") != "1" {
		h.ListAuthFiles(c)
		return
	}
	p := h.isolatedProjectPool()
	if e := p.registerFixtures(c.Request.Context()); e != nil {
		c.JSON(503, gin.H{"error": "account_controller_unavailable"})
		return
	}
	code, b, e := h.containerMetadata(c.Request.Context(), "list", gin.H{})
	if e != nil || code != 200 {
		c.JSON(503, gin.H{"error": "account_controller_unavailable"})
		return
	}
	var data struct {
		Projects []struct {
			Slug     string
			Label    string
			Ready    bool
			Reason   string
			Identity struct{ Email string }
			Routing  map[string]any
			State    map[string]any
		}
	}
	if json.Unmarshal(b, &data) != nil {
		c.Status(502)
		return
	}
	files := []gin.H{}
	for _, project := range data.Projects {
		a, ok := p.manager.GetByID(p.executor.namespace + project.Slug)
		if !ok {
			continue
		}
		if name := c.Query("name"); name != "" && name != project.Slug {
			continue
		}
		if index := c.Query("auth_index"); index != "" && index != a.Index {
			continue
		}
		unavailable, status, message, retry := reconcileAuthFileCooldownState(a, time.Now().UTC())
		if !project.Ready {
			unavailable = true
			message = project.Reason
		}
		label := project.Identity.Email
		if label == "" {
			label = project.Label
		}
		item := gin.H{"id": a.ID, "name": project.Slug, "auth_index": a.Index, "type": "claude", "provider": "claude", "label": label, "email": project.Identity.Email, "status": status, "status_message": message, "disabled": a.Disabled, "unavailable": unavailable, "runtime_only": false, "source": "container", "size": 0, "priority": project.Routing["priority"], "weight": project.Routing["weight"], "route_revision": project.Routing["revision"], "success": a.Success, "failed": a.Failed}
		// Worker publishes only explicitly sanitized, non-secret observations.
		item["container_observation"] = project.State["account_observation"]
		item["quota"] = project.State["quota_observation"]
		item["container_dispatch"] = project.State["model_dispatch"]
		item["container_capabilities"] = gin.H{"version": 1, "account_update": true, "token_refresh": true, "reset_grant": false, "reset_grant_read": true}
		if !retry.IsZero() {
			item["next_retry_after"] = retry
		}
		files = append(files, item)
	}
	c.Header("Cache-Control", "no-store")
	c.JSON(200, gin.H{"files": files})
}
func (h *Handler) ContainerCredentialModels(c *gin.Context) {
	if os.Getenv("CPA_CONTAINER_ROUTING") != "1" {
		h.GetAuthFileModels(c)
		return
	}
	name := c.Query("name")
	if !validProjectSlug(name) {
		c.Status(400)
		return
	}
	p := h.isolatedProjectPool()
	if e := p.registerFixtures(c.Request.Context()); e != nil {
		c.Status(503)
		return
	}
	result := []gin.H{}
	for _, m := range registry.GetGlobalRegistry().GetModelsForClient(p.executor.namespace + name) {
		result = append(result, gin.H{"id": m.ID, "display_name": m.DisplayName, "type": m.Type, "owned_by": m.OwnedBy})
	}
	c.JSON(200, gin.H{"models": result})
}
func (h *Handler) ContainerCredentialFields(c *gin.Context) {
	if os.Getenv("CPA_CONTAINER_ROUTING") != "1" {
		h.PatchAuthFileFields(c)
		return
	}
	var body map[string]json.RawMessage
	dec := json.NewDecoder(io.LimitReader(c.Request.Body, 4097))
	if dec.Decode(&body) != nil {
		c.Status(400)
		return
	}
	var name string
	if json.Unmarshal(body["name"], &name) != nil || !validProjectSlug(name) {
		c.Status(400)
		return
	}
	delete(body, "name")
	changes := gin.H{}
	payload := gin.H{"slug": name, "changes": changes}
	for key, raw := range body {
		switch key {
		case "priority":
			var v int32
			if json.Unmarshal(raw, &v) != nil {
				c.Status(400)
				return
			}
			changes[key] = v
		case "weight":
			var v int64
			if json.Unmarshal(raw, &v) != nil {
				c.Status(400)
				return
			}
			n, e := credentialweight.Normalize(v)
			if e != nil {
				c.Status(400)
				return
			}
			changes[key] = n
		case "route_revision":
			var v int64
			if json.Unmarshal(raw, &v) != nil {
				c.Status(400)
				return
			}
			payload["revision"] = v
		default:
			c.JSON(400, gin.H{"error": "container_route_fields_only"})
			return
		}
	}
	if len(changes) == 0 {
		c.Status(400)
		return
	}
	code, b, e := h.containerMetadata(c.Request.Context(), "route-update", payload)
	if e != nil {
		c.Status(503)
		return
	}
	if code != 200 {
		c.Data(code, "application/json", b)
		return
	}
	if e = h.isolatedProjectPool().registerFixtures(c.Request.Context()); e != nil {
		c.JSON(503, gin.H{"error": "route_saved_sync_pending"})
		return
	}
	c.JSON(200, gin.H{"status": "ok"})
}

func (h *Handler) ContainerResetQuota(c *gin.Context) {
	if os.Getenv("CPA_CONTAINER_ROUTING") != "1" {
		h.ResetQuota(c)
		return
	}
	p := h.isolatedProjectPool()
	if e := p.registerFixtures(c.Request.Context()); e != nil {
		c.Status(503)
		return
	}
	var body struct {
		AuthIndex string `json:"auth_index"`
	}
	if c.ShouldBindJSON(&body) != nil || strings.TrimSpace(body.AuthIndex) == "" {
		c.JSON(400, gin.H{"error": "auth_index is required"})
		return
	}
	var id, slug string
	for _, a := range p.manager.List() {
		if a.Index == strings.TrimSpace(body.AuthIndex) {
			id, slug = a.ID, strings.TrimPrefix(a.ID, p.executor.namespace)
			break
		}
	}
	if id == "" || !validProjectSlug(slug) {
		c.JSON(404, gin.H{"error": "auth not found"})
		return
	}
	// Do not clear the central gate until the bound worker confirms its native
	// reset was persisted. A failed/unknown worker operation remains retryable
	// locally and must never be reported as a successful reset of both layers.
	code, raw, err := h.containerMetadata(c.Request.Context(), "cooldown-reset", gin.H{"slug": slug})
	if err != nil {
		c.JSON(503, gin.H{"error": "container_cooldown_reset_unconfirmed", "central_cleared": false})
		return
	}
	if code != 200 {
		c.Data(code, "application/json", raw)
		return
	}
	var receipt struct {
		Status  string
		Version int
	}
	if json.Unmarshal(raw, &receipt) != nil || receipt.Status != "ok" || receipt.Version != 1 {
		c.JSON(502, gin.H{"error": "invalid_cooldown_reset_receipt", "central_cleared": false})
		return
	}
	updated, models, err := p.manager.ResetQuota(c.Request.Context(), id)
	if err != nil || updated == nil {
		c.JSON(503, gin.H{"error": "central_cooldown_reset_pending", "container_cleared": true, "central_cleared": false})
		return
	}
	c.JSON(200, gin.H{"status": "ok", "auth_index": body.AuthIndex, "models": models, "container_cleared": true, "central_cleared": true})
}

func (h *Handler) ContainerCredentialStatus(c *gin.Context) {
	if os.Getenv("CPA_CONTAINER_ROUTING") != "1" {
		h.PatchAuthFileStatus(c)
		return
	}
	var body struct {
		Name      string `json:"name"`
		Disabled  *bool  `json:"disabled"`
		AuthIndex string `json:"auth_index"`
	}
	if c.ShouldBindJSON(&body) != nil || !validProjectSlug(body.Name) || body.Disabled == nil {
		c.JSON(400, gin.H{"error": "invalid_request"})
		return
	}
	p := h.isolatedProjectPool()
	if err := p.registerFixtures(c.Request.Context()); err != nil {
		c.Status(503)
		return
	}
	a, ok := p.manager.GetByID(p.executor.namespace + body.Name)
	if !ok || (body.AuthIndex != "" && body.AuthIndex != a.Index) {
		c.JSON(409, gin.H{"error": "account_binding_mismatch"})
		return
	}
	code, data, err := h.containerMetadata(c.Request.Context(), "route-update", gin.H{"slug": body.Name, "changes": gin.H{"disabled": *body.Disabled}})
	if err != nil {
		c.Status(503)
		return
	}
	c.Data(code, "application/json", data)
}

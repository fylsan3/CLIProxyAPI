package management

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"net"
	"net/http"
	"os"
	"time"

	"github.com/MoeForge/moego/ojson"
	"github.com/gin-gonic/gin"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/util"
)

func (h *Handler) LocalProjectAdmin(c *gin.Context) {
	action := c.Param("action")
	if action == "refresh" || action == "refresh-all" {
		h.ProjectRefresh(c)
		return
	}
	if action == "pool" {
		h.ProjectPoolStatus(c)
		return
	}
	switch action {
	case "list", "create", "disconnect", "connect", "restart", "history":
	default:
		c.Status(404)
		return
	}
	b, err := io.ReadAll(io.LimitReader(c.Request.Body, 1025))
	if err != nil || len(b) > 1024 {
		c.Status(400)
		return
	}
	h.projectRequest(c, "/admin/"+action, b, false)
}

func (h *Handler) LocalProjectMessages(c *gin.Context, body []byte) {
	if os.Getenv("CPA_CONTAINER_ROUTING") == "1" || ojson.GetBytesNoCopy(body, "model").String() == projectPoolModel {
		var id [16]byte
		if _, err := rand.Read(id[:]); err != nil {
			c.Status(500)
			return
		}
		run := hex.EncodeToString(id[:])
		sum := sha256.Sum256(body)
		c.Header("X-Test-Request", run)
		c.Header("X-Test-Input-SHA256", hex.EncodeToString(sum[:]))
		h.projectSharedMessages(c, body, run, ojson.GetBytesNoCopy(body, "stream").Bool())
		return
	}
	h.projectRequest(c, "/v1/messages", body, true)
}

func (h *Handler) projectRequest(c *gin.Context, path string, body []byte, message bool) {
	ctx, cancel := context.WithCancel(c.Request.Context())
	if !message {
		cancel()
		ctx, cancel = context.WithTimeout(c.Request.Context(), 30*time.Second)
	}
	defer cancel()
	sock := h.containerControlSocket()
	tr := &http.Transport{DisableKeepAlives: true, DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{Timeout: time.Second}).DialContext(ctx, "unix", sock)
	}}
	defer tr.CloseIdleConnections()
	req, err := http.NewRequestWithContext(ctx, "POST", "http://local"+path, bytes.NewReader(body))
	if err != nil {
		c.Status(400)
		return
	}
	if message {
		req.Header = util.ContainerRequestHeaders(c.Request.Header)
		var id [16]byte
		if _, err := rand.Read(id[:]); err != nil {
			c.Status(500)
			return
		}
		run := hex.EncodeToString(id[:])
		sum := sha256.Sum256(body)
		req.Header.Set("X-Test-Request", run)
		c.Header("X-Test-Request", run)
		c.Header("X-Test-Input-SHA256", hex.EncodeToString(sum[:]))
	}
	resp, err := tr.RoundTrip(req)
	if err != nil {
		c.JSON(503, gin.H{"error": gin.H{"type": "api_error", "message": "test_project_controller_unavailable"}})
		return
	}
	defer resp.Body.Close()
	if message && resp.Header.Get("Content-Type") == "text/event-stream" {
		projectCopyHeaders(c, resp.Header)
		c.Status(resp.StatusCode)
		buffer := make([]byte, 8192)
		for {
			n, readErr := resp.Body.Read(buffer)
			if n > 0 {
				if _, writeErr := c.Writer.Write(buffer[:n]); writeErr != nil {
					return
				}
				c.Writer.Flush()
			}
			if readErr != nil {
				return
			}
		}
	}
	reader := io.Reader(resp.Body)
	if !message {
		reader = io.LimitReader(resp.Body, 262145)
	}
	data, err := io.ReadAll(reader)
	if err != nil || (!message && len(data) > 262144) {
		c.Status(502)
		return
	}
	projectCopyHeaders(c, resp.Header)
	c.Header("Cache-Control", "no-store")
	c.Data(resp.StatusCode, "application/json", data)
}

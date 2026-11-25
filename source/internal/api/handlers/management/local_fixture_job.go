package management

import (
	"bytes"
	"context"
	"io"
	"net"
	"net/http"
	"path/filepath"
	"time"

	"github.com/gin-gonic/gin"
)

// LocalFixtureJob can address only the two fixed, offline acceptance workers.
// Production authentication records, model routing and the Docker API are outside this endpoint.
func (h *Handler) LocalFixtureJob(c *gin.Context) {
	who, action := c.Param("owner"), c.Param("action")
	if who != "A" && who != "B" {
		c.Status(http.StatusNotFound)
		return
	}
	switch action {
	case "create", "begin", "approve", "task", "status", "open-browser", "view-browser", "close-browser", "browser-input":
	default:
		c.Status(http.StatusNotFound)
		return
	}
	limitIn := int64(256)
	if action == "browser-input" {
		limitIn = 4096
	}
	if c.Request.ContentLength > limitIn {
		c.Status(http.StatusRequestEntityTooLarge)
		return
	}
	transport := h.fixtureTransport()
	defer transport.CloseIdleConnections()
	client := http.Client{Transport: transport, Timeout: 25 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	var data []byte
	if action == "browser-input" {
		var err error
		data, err = io.ReadAll(io.LimitReader(c.Request.Body, limitIn+1))
		if err != nil || int64(len(data)) > limitIn {
			c.Status(400)
			return
		}
	}
	request, err := http.NewRequestWithContext(c.Request.Context(), http.MethodPost, "http://local/"+who+"/"+action, bytes.NewReader(data))
	if err != nil {
		c.Status(http.StatusInternalServerError)
		return
	}
	res, err := client.Do(request)
	if err != nil {
		c.JSON(503, gin.H{"error": "local_worker_offline"})
		return
	}
	defer res.Body.Close()
	limit := int64(16384)
	if action == "view-browser" || action == "browser-input" {
		limit = 512 * 1024
	}
	body, err := io.ReadAll(io.LimitReader(res.Body, limit+1))
	if err != nil || int64(len(body)) > limit {
		c.Status(http.StatusBadGateway)
		return
	}
	c.Header("Cache-Control", "no-store")
	c.Data(res.StatusCode, "application/json", body)
}

func (h *Handler) fixtureTransport() *http.Transport {
	path := filepath.Join(filepath.Dir(h.configFilePath), ".fixture-control.sock")
	return &http.Transport{DisableKeepAlives: true, DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", path)
	}}
}

// LocalFixtureMessages serves only the reserved offline model names over a Unix socket.
func (h *Handler) LocalFixtureMessages(c *gin.Context, body []byte) {
	if len(body) > 65535 {
		c.Status(http.StatusRequestEntityTooLarge)
		return
	}
	transport := h.fixtureTransport()
	defer transport.CloseIdleConnections()
	req, err := http.NewRequestWithContext(c.Request.Context(), http.MethodPost, "http://local/v1/messages", bytes.NewReader(body))
	if err != nil {
		c.Status(400)
		return
	}
	res, err := transport.RoundTrip(req)
	if err != nil {
		c.JSON(503, gin.H{"error": "fixture_controller_unavailable"})
		return
	}
	defer res.Body.Close()
	c.Header("Content-Type", res.Header.Get("Content-Type"))
	c.Header("Cache-Control", "no-store")
	c.Status(res.StatusCode)
	buf := make([]byte, 8192)
	for {
		n, err := res.Body.Read(buf)
		if n > 0 {
			if _, writeErr := c.Writer.Write(buf[:n]); writeErr != nil {
				return
			}
			c.Writer.Flush()
		}
		if err != nil {
			return
		}
	}
}

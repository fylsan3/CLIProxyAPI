package management

import (
	"bytes"
	"context"
	"io"
	"net"
	"net/http"
	"net/url"

	"github.com/gin-gonic/gin"
)

// AccountConsole bridges management operations only. Provider traffic is unchanged.
func (h *Handler) AccountConsole(c *gin.Context) {
	if origin := c.GetHeader("Origin"); origin != "" {
		u, err := url.Parse(origin)
		scheme := "http"
		if c.Request.TLS != nil && c.Request.TLS.HandshakeComplete {
			scheme = "https"
		}
		if err != nil || u.Scheme != scheme || u.Host != c.Request.Host || u.User != nil || u.Path != "" || u.RawQuery != "" || u.Fragment != "" {
			c.JSON(http.StatusForbidden, gin.H{"error": "origin_mismatch"})
			return
		}
	}
	path := "/admin/dashboard"
	body := []byte("{}")
	if c.Request.Method == http.MethodPost {
		path = "/admin/ui-action"
		var err error
		body, err = io.ReadAll(io.LimitReader(c.Request.Body, 4097))
		if err != nil || len(body) == 0 || len(body) > 4096 {
			c.Status(http.StatusBadRequest)
			return
		}
	}
	sock := h.containerControlSocket()
	tr := &http.Transport{DisableKeepAlives: true, DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "unix", sock)
	}}
	defer tr.CloseIdleConnections()
	req, err := http.NewRequestWithContext(c.Request.Context(), http.MethodPost, "http://local"+path, bytes.NewReader(body))
	if err != nil {
		c.Status(http.StatusBadRequest)
		return
	}
	req.Header.Set("Content-Type", "application/json")
	res, err := tr.RoundTrip(req)
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "account_controller_unavailable"})
		return
	}
	defer func() { _ = res.Body.Close() }()
	data, err := io.ReadAll(io.LimitReader(res.Body, 524289))
	if err != nil || len(data) > 524288 {
		c.Status(http.StatusBadGateway)
		return
	}
	c.Header("Cache-Control", "no-store")
	c.Data(res.StatusCode, "application/json", data)
}

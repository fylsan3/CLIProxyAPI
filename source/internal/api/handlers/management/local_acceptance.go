package management

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"io"
	"net"
	"net/http"
	"path/filepath"
	"regexp"
	"time"

	"github.com/gin-gonic/gin"
)

var acceptanceTicket = regexp.MustCompile(`^[0-9a-f]{32}$`)

// LocalAcceptance reaches only a short-lived socket created by the local operator.
// Neither a CPA credential nor any client-provided upstream address is forwarded.
func (h *Handler) LocalAcceptance(c *gin.Context, body []byte) {
	host, _, err := net.SplitHostPort(c.Request.RemoteAddr)
	ticket := c.GetHeader("X-Local-Check")
	if err != nil || !net.ParseIP(host).IsLoopback() || !acceptanceTicket.MatchString(ticket) {
		c.Status(http.StatusForbidden)
		return
	}
	if len(body) > 2048 {
		c.Status(http.StatusRequestEntityTooLarge)
		return
	}
	path := filepath.Join(filepath.Dir(h.configFilePath), ".one-check", ticket)
	tr := &http.Transport{DisableKeepAlives: true, DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{Timeout: time.Second}).DialContext(ctx, "unix", path)
	}}
	defer tr.CloseIdleConnections()
	req, err := http.NewRequestWithContext(c.Request.Context(), "POST", "http://local/once", bytes.NewReader(body))
	if err != nil {
		c.Status(http.StatusInternalServerError)
		return
	}
	res, err := tr.RoundTrip(req)
	if err != nil {
		c.JSON(503, gin.H{"error": "acceptance_session_unavailable"})
		return
	}
	defer res.Body.Close()
	result, err := io.ReadAll(io.LimitReader(res.Body, 1048577))
	if err != nil || len(result) > 1048576 {
		c.Status(http.StatusBadGateway)
		return
	}
	sum := sha256.Sum256(body)
	c.Header("X-Local-Input-SHA256", hex.EncodeToString(sum[:]))
	c.Header("X-Local-Run", ticket)
	c.Header("Cache-Control", "no-store")
	if id := res.Header.Get("request-id"); id != "" {
		c.Header("request-id", id)
	}
	c.Data(res.StatusCode, "application/json", result)
}

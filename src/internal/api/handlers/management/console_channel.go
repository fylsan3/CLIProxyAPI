package management

import (
	"bufio"
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"time"

	"github.com/gin-gonic/gin"
)

type consoleBinding struct {
	Container, DockerSocket, KeyHash, AcceptanceHash, Model string
	Released                                                bool
}

var consoleID = regexp.MustCompile("^[0-9a-f]{64}$")
var consoleSlots = make(chan struct{}, 8)

func (h *Handler) consoleBinding() (consoleBinding, bool) {
	var b consoleBinding
	data, err := os.ReadFile(filepath.Join(filepath.Dir(h.configFilePath), "console-channel", "binding.json"))
	if err != nil || json.Unmarshal(data, &b) != nil || !consoleID.MatchString(b.Container) || !consoleID.MatchString(b.KeyHash) || !consoleID.MatchString(b.AcceptanceHash) || !filepath.IsAbs(b.DockerSocket) || b.Model == "" {
		return b, false
	}
	return b, true
}
func consoleDocker() string {
	if runtime.GOOS == "darwin" {
		return "/opt/homebrew/bin/docker"
	}
	return "/usr/bin/docker"
}
func consoleReady(ctx context.Context, b consoleBinding) bool {
	probe, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	out, err := exec.CommandContext(probe, consoleDocker(), "--host", "unix://"+b.DockerSocket, "exec", b.Container, "/usr/local/bin/console-relay", "status").Output()
	return err == nil && bytes.Equal(bytes.TrimSpace(out), []byte("true"))
}
func (h *Handler) ConsoleStatus(c *gin.Context) {
	b, ok := h.consoleBinding()
	c.Header("Cache-Control", "no-store")
	if !ok {
		c.JSON(200, gin.H{"state": "unconfigured"})
		return
	}
	state := "acceptance"
	if b.Released {
		state = "released"
	}
	c.JSON(200, gin.H{"state": state, "model": "console/" + b.Model, "container": b.Container[:12], "ready": consoleReady(c.Request.Context(), b)})
}
func channelError(c *gin.Context, status int, reason string) {
	c.JSON(status, gin.H{"type": "error", "error": gin.H{"type": "api_error", "message": reason}})
}

// Capture only one-way hashes before request logging, then discard the private headers.
func DetachConsoleCredentials(c *gin.Context) {
	for _, pair := range [][2]string{{"X-CPA-Channel-Key", "console.channelHash"}, {"X-CPA-Acceptance", "console.acceptanceHash"}} {
		if v := c.GetHeader(pair[0]); v != "" {
			d := sha256.Sum256([]byte(v))
			c.Set(pair[1], hex.EncodeToString(d[:]))
			c.Request.Header.Del(pair[0])
		}
	}
	c.Next()
}
func (h *Handler) ConsoleMessages(c *gin.Context, raw []byte) {
	b, ok := h.consoleBinding()
	if !ok {
		channelError(c, 503, "console_project_unconfigured")
		return
	}
	provided := c.GetString("console.channelHash")
	if subtle.ConstantTimeCompare([]byte(provided), []byte(b.KeyHash)) != 1 {
		channelError(c, 403, "console_project_access_denied")
		return
	}
	if !b.Released {
		trial := c.GetString("console.acceptanceHash")
		if subtle.ConstantTimeCompare([]byte(trial), []byte(b.AcceptanceHash)) != 1 {
			channelError(c, 503, "console_project_not_released")
			return
		}
	}
	if len(raw) > 32<<20 {
		channelError(c, 413, "messages_body_too_large")
		return
	}
	var body map[string]json.RawMessage
	var model string
	if json.Unmarshal(raw, &body) != nil || json.Unmarshal(body["model"], &model) != nil || model != "console/"+b.Model {
		channelError(c, 400, "model_not_enabled")
		return
	}
	body["model"], _ = json.Marshal(b.Model)
	data, err := json.Marshal(body)
	if err != nil {
		channelError(c, 400, "invalid_request")
		return
	}
	select {
	case consoleSlots <- struct{}{}:
		defer func() { <-consoleSlots }()
	default:
		c.Header("Retry-After", "1")
		channelError(c, 429, "console_project_busy")
		return
	}
	ctx, cancel := context.WithCancel(c.Request.Context())
	defer cancel()
	if !consoleReady(ctx, b) {
		channelError(c, 503, "upstream_transport_unavailable")
		return
	}
	bin := consoleDocker()
	cmd := exec.CommandContext(ctx, bin, "--host", "unix://"+b.DockerSocket, "exec", "-i", b.Container, "/usr/local/bin/console-relay", "serve")
	stdin, err := cmd.StdinPipe()
	if err != nil {
		channelError(c, 503, "worker_unavailable")
		return
	}
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		stdin.Close()
		channelError(c, 503, "worker_unavailable")
		return
	}
	if err = cmd.Start(); err != nil {
		stdin.Close()
		channelError(c, 503, "worker_unavailable")
		return
	}
	waited := false
	defer func() {
		stdin.Close()
		cancel()
		if !waited {
			cmd.Wait()
		}
	}()
	req, _ := http.NewRequestWithContext(ctx, "POST", "http://worker/v1/messages", bytes.NewReader(data))
	for _, k := range []string{"Anthropic-Version", "Anthropic-Beta"} {
		if v := c.GetHeader(k); v != "" {
			req.Header.Set(k, v)
		}
	}
	if err = req.Write(stdin); err != nil {
		channelError(c, 503, "worker_unavailable")
		return
	}
	reader := bufio.NewReaderSize(stdout, 32768)
	line, err := reader.ReadSlice('\n')
	var meta struct {
		Status int
		Header http.Header
		Worker string
	}
	if err != nil || json.Unmarshal(line, &meta) != nil || meta.Worker != b.Container[:12] || meta.Status < 200 || meta.Status > 599 {
		channelError(c, 503, "invalid_worker_receipt")
		return
	}
	var id [16]byte
	if _, err = rand.Read(id[:]); err != nil {
		channelError(c, 500, "request_id_unavailable")
		return
	}
	for k, vv := range meta.Header {
		for _, v := range vv {
			c.Writer.Header().Add(k, v)
		}
	}
	c.Header("X-CPA-Request", hex.EncodeToString(id[:]))
	c.Header("X-CPA-Executor", meta.Worker)
	c.Header("Cache-Control", "no-store")
	c.Status(meta.Status)
	received := sha256.New()
	buf := make([]byte, 32*1024)
	for {
		n, e := reader.Read(buf)
		if n > 0 {
			if !b.Released {
				received.Write(buf[:n])
			}
			if _, err = c.Writer.Write(buf[:n]); err != nil {
				return
			}
			c.Writer.Flush()
		}
		if e != nil {
			if e != io.EOF {
				panic(http.ErrAbortHandler)
			}
			break
		}
	}
	// A truncated SSE stream must not be completed with a synthetic event.
	stdin.Close()
	err = cmd.Wait()
	waited = true
	if err != nil && ctx.Err() == nil {
		panic(http.ErrAbortHandler)
	}
	if !b.Released && err == nil && ctx.Err() == nil && (meta.Status == 200 || (meta.Status >= 400 && meta.Status < 500)) && meta.Header.Get("Request-Id") != "" {
		kind := "message"
		if string(body["stream"]) == "true" {
			kind = "stream"
		}
		if meta.Status >= 400 {
			kind = "error"
		}
		record := gin.H{"status": meta.Status, "request": hex.EncodeToString(id[:]), "executor": meta.Worker, "upstream_request": meta.Header.Get("Request-Id"), "sha256": hex.EncodeToString(received.Sum(nil)), "completed": time.Now().UTC(), "model": b.Model}
		directory := filepath.Join(filepath.Dir(h.configFilePath), "console-channel")
		if f, e := os.CreateTemp(directory, ".receipt-"); e == nil {
			name := f.Name()
			e = json.NewEncoder(f).Encode(record)
			closeErr := f.Close()
			if e == nil && closeErr == nil {
				os.Rename(name, filepath.Join(directory, "last-"+kind+".json"))
			}
			os.Remove(name)
		}
	}

}

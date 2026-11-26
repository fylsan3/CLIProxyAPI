//go:build cpa_offline

package main

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"

	"golang.org/x/net/proxy"
)

const accountNetworkUID = 1002

type accountNetworkConfig struct {
	Owner          string `json:"owner"`
	Provider       string `json:"provider"`
	ProxyIP        string `json:"proxy_ip"`
	ProxyPort      int    `json:"proxy_port"`
	Username       string `json:"username"`
	Password       string `json:"password"`
	CheckMode      string `json:"check_mode"`
	CheckHost      string `json:"check_host"`
	CheckPort      int    `json:"check_port"`
	ExpectedEgress string `json:"expected_egress"`
	Timezone       string `json:"timezone"`
	TestOnly       bool   `json:"test_only"`
}

func readAccountNetworkConfig(r io.Reader) (accountNetworkConfig, error) {
	var c accountNetworkConfig
	if err := json.NewDecoder(io.LimitReader(r, 16385)).Decode(&c); err != nil {
		return c, errors.New("invalid_proxy_config")
	}
	if !regexp.MustCompile(`^[A-Z][A-Z0-9-]{0,31}$`).MatchString(c.Owner) || strings.HasSuffix(c.Owner, "-") ||
		net.ParseIP(c.ProxyIP) == nil || c.ProxyPort < 1 || c.ProxyPort > 65535 || len(c.Username) < 1 || len(c.Username) > 255 || len(c.Password) < 1 || len(c.Password) > 255 {
		return c, errors.New("invalid_proxy_config")
	}
	if c.Provider != "claude-subscription" && c.Provider != "mock-claude" {
		return c, errors.New("invalid_proxy_config")
	}
	if c.TestOnly {
		if c.Provider != "mock-claude" || c.CheckHost != strings.ToLower(c.Owner)+".upstream.invalid" || c.CheckPort < 1 || c.CheckPort > 65535 {
			return c, errors.New("invalid_proxy_config")
		}
	} else if c.CheckMode != "https_exit" {
		return c, errors.New("invalid_proxy_config")
	}
	return c, nil
}

type accountNetwork struct {
	config      accountNetworkConfig
	mu          sync.Mutex
	result      map[string]any
	healthy     bool
	checked     bool
	active      int
	failures    uint64
	lastSuccess int64
	connections map[net.Conn]struct{}
}

func newAccountNetwork(c accountNetworkConfig) *accountNetwork {
	return &accountNetwork{config: c, connections: make(map[net.Conn]struct{}), result: map[string]any{"healthy": false, "reason": "startup_network_pending", "services": []any{}}}
}

// Only this process (UID 1002) is permitted by the kernel to contact the bound
// SOCKS peer. Numeric peer addressing never invokes the container DNS resolver.
// x/net SOCKS wraps net.Conn and hides TCP CloseWrite. Retain the underlying
// TCP connection so EOF in one direction does not deadlock the other direction.
type halfCloseDialer struct {
	net.Dialer
	raw net.Conn
}

func (d *halfCloseDialer) Dial(network, address string) (net.Conn, error) {
	return d.DialContext(context.Background(), network, address)
}
func (d *halfCloseDialer) DialContext(ctx context.Context, network, address string) (net.Conn, error) {
	c, e := d.Dialer.DialContext(ctx, network, address)
	d.raw = c
	return c, e
}

type halfCloseConn struct {
	net.Conn
	raw net.Conn
}

func (c *halfCloseConn) CloseWrite() error {
	if w, ok := c.raw.(interface{ CloseWrite() error }); ok {
		return w.CloseWrite()
	}
	return errors.New("half_close_unsupported")
}

func (n *accountNetwork) dial(ctx context.Context, destination string) (net.Conn, error) {
	forward := &halfCloseDialer{Dialer: net.Dialer{Timeout: 7 * time.Second}}
	d, err := proxy.SOCKS5("tcp", net.JoinHostPort(n.config.ProxyIP, strconv.Itoa(n.config.ProxyPort)),
		&proxy.Auth{User: n.config.Username, Password: n.config.Password}, forward)
	if err != nil {
		return nil, errors.New("invalid_proxy_config")
	}
	cd, ok := d.(proxy.ContextDialer)
	if !ok {
		return nil, errors.New("proxy_context_required")
	}
	conn, err := cd.DialContext(ctx, "tcp", destination)
	if err != nil {
		n.mu.Lock()
		n.failures++
		n.mu.Unlock()
		if errors.Is(err, context.DeadlineExceeded) {
			return nil, errors.New("proxy_check_timeout")
		}
		if strings.Contains(err.Error(), "username/password authentication failed") {
			return nil, errors.New("proxy_auth_rejected")
		}
		return nil, errors.New("proxy_connection_failed")
	}
	return &halfCloseConn{Conn: conn, raw: forward.raw}, nil
}

func (n *accountNetwork) probeHTTP(ctx context.Context, endpoint, kind string) ([]byte, error) {
	tr := &http.Transport{DialContext: func(ctx context.Context, network, address string) (net.Conn, error) { return n.dial(ctx, address) }, DisableKeepAlives: true}
	defer tr.CloseIdleConnections()
	client := &http.Client{Transport: tr, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	req, err := http.NewRequestWithContext(ctx, "GET", endpoint, nil)
	if err != nil {
		return nil, err
	}
	applyNetworkCheckHeaders(req, kind)
	res, err := client.Do(req)
	if err != nil {
		return nil, errors.New("exit_service_unavailable")
	}
	defer res.Body.Close()
	b, err := io.ReadAll(io.LimitReader(res.Body, 8193))
	if err != nil || res.StatusCode != 200 || len(b) > 8192 {
		return nil, errors.New("exit_service_response_invalid")
	}
	return b, nil
}

func (n *accountNetwork) location(ctx context.Context) (map[string]any, error) {
	endpoint := "https://ipwho.is/?fields=ip,success,timezone.id"
	if n.config.TestOnly {
		endpoint = "http://" + net.JoinHostPort(n.config.CheckHost, strconv.Itoa(n.config.CheckPort)) + "/location-check"
	}
	b, err := n.probeHTTP(ctx, endpoint, "location")
	if err != nil {
		return nil, err
	}
	var v struct {
		IP       string `json:"ip"`
		Success  bool   `json:"success"`
		Timezone struct {
			ID string `json:"id"`
		} `json:"timezone"`
	}
	if json.Unmarshal(b, &v) != nil || !v.Success || net.ParseIP(v.IP) == nil {
		return nil, errors.New("location_unavailable")
	}
	if n.config.ExpectedEgress != "" && !net.ParseIP(v.IP).Equal(net.ParseIP(n.config.ExpectedEgress)) {
		return nil, errors.New("exit_mismatch")
	}
	if _, err = time.LoadLocation(v.Timezone.ID); err != nil || v.Timezone.ID == "" || len(v.Timezone.ID) > 100 {
		return nil, errors.New("invalid_timezone")
	}
	source := "ipwho.is"
	if n.config.TestOnly {
		source = "fixture"
	}
	return map[string]any{"exit_ip": net.ParseIP(v.IP).String(), "timezone": v.Timezone.ID, "language": "en-US", "observed_at": time.Now().Unix(), "source": source}, nil
}

func (n *accountNetwork) initialCheck(ctx context.Context) {
	result := map[string]any{"healthy": false, "reason": "network_check_failed", "network_checked_at": time.Now().Unix(), "check_mode": "startup_only", "services": []map[string]any{}}
	defer func() {
		n.mu.Lock()
		n.result = result
		n.healthy = result["healthy"] == true
		n.checked = true
		if n.healthy {
			n.lastSuccess = time.Now().Unix()
		}
		n.mu.Unlock()
	}()
	endpoints := []struct{ host, path, kind string }{{"api.ipify.org", "/?format=json", "json"}, {"www.cloudflare.com", "/cdn-cgi/trace", "trace"}}
	if n.config.TestOnly {
		endpoints = []struct{ host, path, kind string }{{n.config.CheckHost, "/network-check", "fixture"}}
	}
	services := []map[string]any{}
	for _, e := range endpoints {
		target := "https://" + e.host + e.path
		if e.kind == "fixture" {
			target = "http://" + net.JoinHostPort(e.host, strconv.Itoa(n.config.CheckPort)) + e.path
		}
		sub, cancel := context.WithTimeout(ctx, 20*time.Second)
		b, err := n.probeHTTP(sub, target, "exit")
		cancel()
		ip := ""
		if err == nil {
			if e.kind == "trace" {
				for _, line := range strings.Split(string(b), "\n") {
					if strings.HasPrefix(line, "ip=") {
						ip = strings.TrimPrefix(line, "ip=")
					}
				}
			} else {
				var v map[string]any
				err = json.Unmarshal(b, &v)
				if e.kind == "fixture" {
					if v["owner"] != n.config.Owner {
						err = errors.New("exit_owner_mismatch")
					}
					ip, _ = v["egress"].(string)
				} else {
					ip, _ = v["ip"].(string)
				}
			}
		}
		valid := err == nil && net.ParseIP(ip) != nil
		services = append(services, map[string]any{"service": e.host, "ok": valid})
		result["services"] = services
		if !valid {
			continue
		}
		result["exit_ip"] = net.ParseIP(ip).String()
		if net.ParseIP(ip).Equal(net.ParseIP(n.config.ExpectedEgress)) {
			result["healthy"] = true
			result["reason"] = "network_verified"
		} else {
			result["reason"] = "exit_changed"
		}
		break // An observed mismatch must never be hidden by another service.
	}
	if result["healthy"] == true && n.config.Timezone != "" {
		result["timezone_checked_at"] = time.Now().Unix()
		result["timezone_warning"] = true
		result["timezone_check_reason"] = "timezone_check_failed"
		sub, cancel := context.WithTimeout(ctx, 20*time.Second)
		location, err := n.location(sub)
		cancel()
		if err == nil {
			observed := location["timezone"]
			result["observed_timezone"] = observed
			result["timezone_warning"] = observed != n.config.Timezone
			if observed == n.config.Timezone {
				result["timezone_check_reason"] = "timezone_verified"
			} else {
				result["timezone_check_reason"] = "timezone_changed"
			}
		}
	}
}

func (n *accountNetwork) publish(root string) error {
	n.mu.Lock()
	v := make(map[string]any)
	for k, x := range n.result {
		v[k] = x
	}
	v["owner"] = n.config.Owner
	v["checked_at"] = float64(time.Now().UnixNano()) / 1e9
	v["healthy"] = n.healthy
	v["observation_healthy"] = n.healthy
	v["observation_reason"] = n.result["reason"]
	v["warning"] = false
	v["fixed_timezone"] = n.config.Timezone
	v["periodic_network_checks"] = false
	v["idle_check_interval_seconds"] = nil
	v["checking"] = !n.checked
	v["active_connections"] = n.active
	v["next_check_in_seconds"] = nil
	v["last_success_at"] = n.lastSuccess
	v["egress_manager"] = "go"
	v["header_policy_version"] = accountHeaderPolicyVersion
	v["connect_failures"] = n.failures
	n.mu.Unlock()
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	tmp := filepath.Join(root, "status.pending")
	if err = os.WriteFile(tmp, b, 0644); err != nil {
		return err
	}
	if err = os.Chmod(tmp, 0644); err != nil {
		return err
	}
	return os.Rename(tmp, filepath.Join(root, "status.json"))
}

func readSOCKSDestination(r io.Reader) (string, error) {
	var one [1]byte
	if _, err := io.ReadFull(r, one[:]); err != nil {
		return "", err
	}
	var host string
	switch one[0] {
	case 1:
		b := make([]byte, 4)
		if _, err := io.ReadFull(r, b); err != nil {
			return "", err
		}
		host = net.IP(b).String()
	case 4:
		b := make([]byte, 16)
		if _, err := io.ReadFull(r, b); err != nil {
			return "", err
		}
		host = net.IP(b).String()
	case 3:
		if _, err := io.ReadFull(r, one[:]); err != nil || one[0] == 0 {
			return "", errors.New("bad_domain")
		}
		b := make([]byte, int(one[0]))
		if _, err := io.ReadFull(r, b); err != nil {
			return "", err
		}
		host = string(b)
	default:
		return "", errors.New("bad_address")
	}
	var p [2]byte
	if _, err := io.ReadFull(r, p[:]); err != nil {
		return "", err
	}
	port := binary.BigEndian.Uint16(p[:])
	if port == 0 {
		return "", errors.New("bad_port")
	}
	return net.JoinHostPort(host, strconv.Itoa(int(port))), nil
}

func (n *accountNetwork) allowedDestination(destination string) bool {
	host, port, err := net.SplitHostPort(destination)
	if err != nil {
		return false
	}
	if n.config.TestOnly {
		return host == n.config.CheckHost && port == strconv.Itoa(n.config.CheckPort)
	}
	if port != "443" && port != "80" {
		return false
	}
	if strings.EqualFold(host, "localhost") || strings.HasSuffix(strings.ToLower(host), ".localhost") {
		return false
	}
	if ip := net.ParseIP(host); ip != nil && (ip.IsLoopback() || ip.IsUnspecified() || ip.IsLinkLocalUnicast() || ip.IsMulticast()) {
		return false
	}
	return !strings.ContainsAny(host, "\x00\r\n/\\")
}

func (n *accountNetwork) handle(ctx context.Context, local net.Conn) {
	n.mu.Lock()
	ready := n.healthy
	if ready {
		n.active++
		n.connections[local] = struct{}{}
	}
	n.mu.Unlock()
	defer local.Close()
	if !ready {
		return
	}
	defer func() { n.mu.Lock(); n.active--; delete(n.connections, local); n.mu.Unlock() }()
	_ = local.SetDeadline(time.Now().Add(10 * time.Second))
	var greeting [2]byte
	if _, err := io.ReadFull(local, greeting[:]); err != nil || greeting[0] != 5 {
		return
	}
	methods := make([]byte, int(greeting[1]))
	if _, err := io.ReadFull(local, methods); err != nil {
		return
	}
	found := false
	for _, m := range methods {
		if m == 0 {
			found = true
		}
	}
	if !found {
		_, _ = local.Write([]byte{5, 255})
		return
	}
	if _, err := local.Write([]byte{5, 0}); err != nil {
		return
	}
	var header [3]byte
	if _, err := io.ReadFull(local, header[:]); err != nil || header != [3]byte{5, 1, 0} {
		return
	}
	destination, err := readSOCKSDestination(local)
	if err != nil || !n.allowedDestination(destination) {
		return
	}
	dialCtx, cancel := context.WithTimeout(ctx, 7*time.Second)
	remote, err := n.dial(dialCtx, destination)
	cancel()
	if err != nil {
		_, _ = local.Write([]byte{5, 1, 0, 1, 0, 0, 0, 0, 0, 0})
		return
	}
	defer remote.Close()
	n.mu.Lock()
	n.connections[remote] = struct{}{}
	n.mu.Unlock()
	defer func() { n.mu.Lock(); delete(n.connections, remote); n.mu.Unlock() }()
	if _, err = local.Write([]byte{5, 0, 0, 1, 0, 0, 0, 0, 0, 0}); err != nil {
		return
	}
	_ = local.SetDeadline(time.Time{})
	// Established streams have no duration or idle cutoff. Half-close propagates
	// cancellation without truncating the other direction's remaining response.
	done := make(chan error, 2)
	pump := func(dst, src net.Conn) {
		_, err := io.Copy(dst, src)
		if tcp, ok := dst.(interface{ CloseWrite() error }); ok {
			_ = tcp.CloseWrite()
		}
		done <- err
	}
	go pump(remote, local)
	go pump(local, remote)
	if err = <-done; err != nil {
		_ = remote.Close()
		_ = local.Close()
	}
	<-done
}

func runAccountNetwork(probeOnly bool) error {
	if os.Geteuid() != accountNetworkUID {
		return errors.New("network_process_identity_invalid")
	}
	c, err := readAccountNetworkConfig(os.Stdin)
	if err != nil {
		return err
	}
	n := newAccountNetwork(c)
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGTERM, syscall.SIGINT)
	defer stop()
	if probeOnly {
		sub, cancel := context.WithTimeout(ctx, 20*time.Second)
		defer cancel()
		_ = json.NewEncoder(os.Stdout).Encode(map[string]string{"step": "checking_exit"})
		location, err := n.location(sub)
		if err != nil {
			_ = json.NewEncoder(os.Stdout).Encode(map[string]string{"error": "exit_timezone_unavailable"})
			return err
		}
		return json.NewEncoder(os.Stdout).Encode(map[string]any{"location": location})
	}
	if c.Owner != os.Getenv("FIXTURE_OWNER") || net.ParseIP(c.ExpectedEgress) == nil {
		return errors.New("network_binding_mismatch")
	}
	listener, err := net.Listen("tcp", "127.0.0.1:1080")
	if err != nil {
		return err
	}
	defer listener.Close()
	go n.initialCheck(ctx)
	go func() {
		<-ctx.Done()
		_ = listener.Close()
		n.mu.Lock()
		for conn := range n.connections {
			_ = conn.Close()
		}
		n.mu.Unlock()
	}()
	heartbeatDone := make(chan struct{})
	defer close(heartbeatDone)
	go func() {
		ticker := time.NewTicker(500 * time.Millisecond)
		defer ticker.Stop()
		for {
			if n.publish("/run/network/live") != nil {
				stop()
				return
			}
			select {
			case <-heartbeatDone:
				return
			case <-ctx.Done():
				return
			case <-ticker.C:
			}
		}
	}()
	for {
		conn, err := listener.Accept()
		if err != nil {
			if ctx.Err() != nil {
				return nil
			}
			return fmt.Errorf("network_listener_failed")
		}
		go n.handle(ctx, conn)
	}
}

// Local-only resource observation; never sent to a provider or used as headers.
func accountResourceSnapshot() map[string]any {
	result := map[string]any{}
	for name, file := range map[string]string{"memory_current_bytes": "memory.current", "memory_limit_bytes": "memory.max", "memory_peak_bytes": "memory.peak"} {
		if b, err := os.ReadFile("/sys/fs/cgroup/" + file); err == nil {
			if n, err := strconv.ParseUint(strings.TrimSpace(string(b)), 10, 64); err == nil {
				result[name] = n
			}
		}
	}
	if b, err := os.ReadFile("/sys/fs/cgroup/memory.events"); err == nil {
		for _, line := range strings.Split(string(b), "\n") {
			parts := strings.Fields(line)
			if len(parts) == 2 && (parts[0] == "oom" || parts[0] == "oom_kill") {
				if n, err := strconv.ParseUint(parts[1], 10, 64); err == nil {
					result[parts[0]] = n
				}
			}
		}
	}
	var event struct {
		Observed int64 `json:"observed_at"`
		Kills    int   `json:"new_oom_kills"`
	}
	if b, err := os.ReadFile("/state/browser-memory-diagnostics.json"); err == nil && json.Unmarshal(b, &event) == nil && event.Observed > 0 && event.Kills > 0 {
		result["last_oom_at"] = event.Observed
		result["last_oom_kills"] = event.Kills
	}
	return result
}

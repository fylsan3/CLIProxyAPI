//go:build cpa_offline

package main

import (
	"bytes"
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"errors"
	"fmt"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/config"
	native "github.com/router-for-me/CLIProxyAPI/v8/internal/runtime/executor"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/util"
	coreauth "github.com/router-for-me/CLIProxyAPI/v8/sdk/cliproxy/auth"
	execution "github.com/router-for-me/CLIProxyAPI/v8/sdk/cliproxy/executor"
	translator "github.com/router-for-me/CLIProxyAPI/v8/sdk/translator"
	"io"
	"math/big"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"
)

func TestProviderHTTPSPreservesPayloadAndRejectsUntrustedCertificate(t *testing.T) {
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	template := &x509.Certificate{SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "local fixture"}, DNSNames: []string{"api.anthropic.com"}, NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour), KeyUsage: x509.KeyUsageDigitalSignature | x509.KeyUsageCertSign, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}, IsCA: true, BasicConstraintsValid: true}
	der, err := x509.CreateCertificate(rand.Reader, template, template, &key.PublicKey, key)
	if err != nil {
		t.Fatal(err)
	}
	certificate, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	payload := []byte(`{"model":"claude-sonnet-4-5","messages":[{"role":"user","content":"fixture"}]}`)
	server := httptest.NewUnstartedServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		if r.Host != "api.anthropic.com" || r.URL.Path != "/v1/messages" || !bytes.Equal(raw, payload) {
			t.Error("request changed")
		}
		if r.Header.Get("X-Offline-Owner") != "" || r.Header.Get("X-Offline-Run") != "" || r.Header.Get("X-Offline-Attempt") != "" {
			t.Error("fixture headers leaked")
		}
		w.WriteHeader(403)
		_, _ = w.Write([]byte("original error body"))
	}))
	server.TLS = &tls.Config{Certificates: []tls.Certificate{{Certificate: [][]byte{der}, PrivateKey: key}}}
	server.StartTLS()
	defer server.Close()
	base := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "tcp", server.Listener.Addr().String())
	}}
	defer base.CloseIdleConnections()
	transport := &providerTransport{base: base, owner: "A", provider: "claude-subscription"}
	makeRequest := func() *http.Request {
		r, _ := http.NewRequest("POST", "https://api.anthropic.com/v1/messages", bytes.NewReader(payload))
		return r.WithContext(context.WithValue(r.Context(), offlineTraceKey{}, offlineTrace{Run: "test", Attempt: "test"}))
	}
	if response, err := transport.RoundTrip(makeRequest()); err == nil {
		response.Body.Close()
		t.Fatal("untrusted certificate accepted")
	}
	roots := x509.NewCertPool()
	roots.AddCert(certificate)
	base.TLSClientConfig = &tls.Config{RootCAs: roots}
	response, err := transport.RoundTrip(makeRequest())
	if err != nil {
		t.Fatal(err)
	}
	defer response.Body.Close()
	raw, _ := io.ReadAll(response.Body)
	if response.StatusCode != 403 || string(raw) != "original error body" || len(response.TLS.VerifiedChains) == 0 {
		t.Fatal("response or verification changed")
	}
}

func TestProviderRejectsUnexpectedDestinationBeforeDial(t *testing.T) {
	calls := 0
	base := &http.Transport{DialContext: func(context.Context, string, string) (net.Conn, error) {
		calls++
		t.Fatal("unexpected dial")
		return nil, nil
	}}
	transport := &providerTransport{base: base, provider: "claude-subscription"}
	for _, url := range []string{"http://api.anthropic.com/v1/messages", "https://example.invalid/v1/messages", "https://api.anthropic.com:444/v1/messages", "https://user@api.anthropic.com/v1/messages", "https://api.anthropic.com/private"} {
		r, _ := http.NewRequest("POST", url, nil)
		if _, err := transport.RoundTrip(r); err == nil {
			t.Fatal("unexpected destination accepted")
		}
	}
	if calls != 0 {
		t.Fatal("unexpected dial")
	}
}

func TestMockProviderRetainsRewriteWithoutMutatingOriginal(t *testing.T) {
	t.Setenv("CPA_PROVIDER", "mock-claude")
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Host != "a.upstream.invalid:8080" || r.Header.Get("X-Offline-Owner") != "A" || r.Header.Get("X-Offline-Run") != "mock-run" {
			t.Error("mock binding changed")
		}
		w.WriteHeader(204)
	}))
	defer server.Close()
	base := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "tcp", server.Listener.Addr().String())
	}}
	defer base.CloseIdleConnections()
	transport := &providerTransport{base: base, owner: "A", provider: "mock-claude"}
	req, _ := http.NewRequest("POST", "https://api.anthropic.com/v1/messages", nil)
	req = req.WithContext(context.WithValue(req.Context(), offlineTraceKey{}, offlineTrace{Run: "mock-run"}))
	response, err := transport.RoundTrip(req)
	if err != nil {
		t.Fatal(err)
	}
	response.Body.Close()
	if response.StatusCode != 204 || req.URL.Host != "api.anthropic.com" || req.Header.Get("X-Offline-Owner") != "" {
		t.Fatal("original request mutated")
	}
}

type countFixtureTransport func(*http.Request) (*http.Response, error)

func (f countFixtureTransport) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

type interruptedCountBody struct{ sent bool }

func (b *interruptedCountBody) Read(p []byte) (int, error) {
	if b.sent {
		return 0, io.ErrUnexpectedEOF
	}
	b.sent = true
	return copy(p, `{"type":"error","error":{"message":"incomplete`), nil
}
func TestNativeCountErrorPreservesOnlyCompleteBody(t *testing.T) {
	payload := []byte(`{"model":"claude-sonnet-4-6","messages":[{"role":"user","content":"fixture"}]}`)
	original := "{\"type\":\"error\",\"error\":{\"type\":\"permission_error\",\"message\":\"fixture denied\"}}\n"
	for _, complete := range []bool{true, false} {
		t.Run(fmt.Sprint(complete), func(t *testing.T) {
			transport := countFixtureTransport(func(r *http.Request) (*http.Response, error) {
				if r.URL.Host != "api.anthropic.com" || r.URL.Path != "/v1/messages/count_tokens" {
					t.Fatal("unexpected count destination")
				}
				var body io.Reader = strings.NewReader(original)
				if !complete {
					body = &interruptedCountBody{}
				}
				return &http.Response{StatusCode: 403, Header: http.Header{"Content-Type": []string{"application/json"}}, Body: io.NopCloser(body)}, nil
			})
			ctx := context.WithValue(context.Background(), "cliproxy.roundtripper", http.RoundTripper(transport))
			executor := native.NewClaudeExecutor(&config.Config{DisableClaudeCloakMode: true})
			auth := &coreauth.Auth{ID: "fixture-count", Provider: "claude", Metadata: map[string]any{"access_token": "sk-ant-oat01-fixture-test", "cloak_mode": "never"}}
			_, err := executor.CountTokens(ctx, auth, execution.Request{Model: "claude-sonnet-4-6", Payload: payload}, execution.Options{SourceFormat: translator.FromString("claude"), ResponseFormat: translator.FromString("claude"), OriginalRequest: payload})
			if err == nil {
				t.Fatal("expected upstream rejection")
			}
			var raw interface{ ClaudeResponseBody() (string, bool) }
			if !errors.As(err, &raw) {
				t.Fatal("native classification missing")
			}
			body, preserved := raw.ClaudeResponseBody()
			if preserved != complete || (complete && body != original) {
				t.Fatal("complete/partial body classification changed")
			}
			out := httptest.NewRecorder()
			nativeError(out, err)
			if out.Code != 403 || (complete && out.Body.String() != original) || (!complete && out.Body.String() == body) {
				t.Fatal("incorrect error forwarding")
			}
		})
	}
}

func TestContainerHeaderBoundary(t *testing.T) {
	src := http.Header{"Anthropic-Beta": {"one", "two"}, "Accept": {"application/json"}, "Authorization": {"private"}, "Cookie": {"private"}, "X-Stainless-Os": {"private"}}
	got := util.ContainerRequestHeaders(src)
	if len(got) != 3 || len(got.Values("Anthropic-Beta")) != 2 || got.Get("X-Stainless-Os") != "private" {
		t.Fatalf("unexpected protocol headers: %v", got)
	}
	src.Set("Connection", "Anthropic-Beta")
	if util.ContainerRequestHeaders(src).Get("Anthropic-Beta") != "" {
		t.Fatal("hop scoped request escaped")
	}
	src = http.Header{"Retry-After": {"2"}, "X-Feature": {"one", "two"}, "X-Litellm-Test": {"keep"}, "Set-Cookie": {"private"}, "Connection": {"X-Hop"}, "X-Hop": {"private"}, "X-Test-Container": {"spoof"}, "Content-Encoding": {"gzip"}}
	got = util.ContainerResponseHeaders(src)
	if len(got) != 3 || len(got.Values("X-Feature")) != 2 || got.Get("X-Litellm-Test") != "keep" {
		t.Fatalf("unexpected response headers %v", got)
	}
	got["X-Feature"][0] = "mutated"
	if src.Get("X-Feature") != "one" {
		t.Fatal("header alias")
	}
}
func TestConcurrentHeaderCaptureAndRawError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Feature-Owner", r.Header.Get("X-Owner"))
		w.Header().Add("X-Feature", "one")
		w.Header().Add("X-Feature", "two")
		w.Header().Set("Content-Type", "application/problem+json")
		w.Header().Set("Retry-After", "2")
		w.Header().Set("Set-Cookie", "private")
		w.WriteHeader(403)
		io.WriteString(w, "original")
	}))
	defer server.Close()
	base := &http.Transport{DialContext: func(ctx context.Context, _, _ string) (net.Conn, error) {
		return (&net.Dialer{}).DialContext(ctx, "tcp", server.Listener.Addr().String())
	}}
	defer base.CloseIdleConnections()
	transport := &providerTransport{base: base, provider: "mock-claude", owner: "A"}
	var wg sync.WaitGroup
	for _, owner := range []string{"A", "B"} {
		wg.Add(1)
		go func(owner string) {
			defer wg.Done()
			capture := &providerHeaderCapture{}
			ctx := context.WithValue(context.Background(), providerHeadersKey{}, capture)
			req, _ := http.NewRequestWithContext(ctx, "POST", "https://api.anthropic.com/v1/messages", nil)
			req.Header.Set("X-Owner", owner)
			response, err := transport.RoundTrip(req)
			if err != nil {
				t.Error(err)
				return
			}
			io.Copy(io.Discard, response.Body)
			response.Body.Close()
			h := capture.get()
			if h.Get("X-Feature-Owner") != owner || h.Get("Set-Cookie") != "" {
				t.Errorf("wrong captured headers: %v", h)
			}
			out := httptest.NewRecorder()
			nativeError(out, headerFixtureError{}, h)
			if out.Code != 403 || out.Body.String() != "original" || out.Header().Get("Retry-After") != "2" || out.Header().Get("Content-Type") != "application/problem+json" || len(out.Header().Values("X-Feature")) != 2 {
				t.Error("raw error header mismatch")
			}
		}(owner)
	}
	wg.Wait()
}

type headerFixtureError struct{}

func (headerFixtureError) Error() string                      { return "fixture" }
func (headerFixtureError) StatusCode() int                    { return 403 }
func (headerFixtureError) ClaudeResponseBody() (string, bool) { return "original", true }

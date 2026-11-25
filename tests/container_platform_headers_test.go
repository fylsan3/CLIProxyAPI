package main

import (
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"syscall"
	"testing"
)

func TestContainerPlatformNormalization(t *testing.T) {
	for _, c := range []struct{ os, arch, wantOS, wantArch string }{
		{"Linux", "aarch64", "Linux", "arm64"}, {"Linux", "x86_64", "Linux", "x64"},
		{"linux", "armv7l", "Linux", "arm"}, {"Linux", "i686", "Linux", "x32"},
		{"unexpected", "unexpected", "Unknown", "unknown"},
	} {
		os, arch := normalizeContainerPlatform(c.os, c.arch)
		if os != c.wantOS || arch != c.wantArch {
			t.Fatalf("%+v: got %s/%s", c, os, arch)
		}
	}
}

func TestActualContainerAndWire(t *testing.T) {
	var u syscall.Utsname
	if err := syscall.Uname(&u); err != nil {
		t.Fatal(err)
	}
	var system, machine strings.Builder
	for _, c := range u.Sysname {
		if c == 0 {
			break
		}
		system.WriteByte(byte(c))
	}
	for _, c := range u.Machine {
		if c == 0 {
			break
		}
		machine.WriteByte(byte(c))
	}
	wantOS, wantArch := normalizeContainerPlatform(system.String(), machine.String())
	if wantOS == "Unknown" || wantArch == "unknown" {
		t.Fatal("test container platform is unknown")
	}
	const body = `{"messages":[{"role":"user","content":"timezone: Asia/Tokyo; system language: zh-CN"}]}`
	for _, path := range []string{"/v1/messages", "/v1/messages/count_tokens"} {
		t.Run(path, func(t *testing.T) {
			received := make(chan http.Header, 1)
			payload := make(chan string, 1)
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				b, _ := io.ReadAll(r.Body)
				received <- r.Header.Clone()
				payload <- string(b)
				w.Write([]byte("OK"))
			}))
			defer server.Close()
			req, _ := http.NewRequest("POST", server.URL+path, strings.NewReader(body))
			req.Header = http.Header{"x-stainless-os": {"Windows"}, "X-Stainless-OS": {"MacOS"}, "x-stainless-arch": {"x64"}, "X-Stainless-Arch": {"x32"}, "X-Timezone": {"Asia/Tokyo"}, "Accept-Language": {"zh-CN"}, "Anthropic-Version": {"caller-version"}}
			baseline := req.Clone(req.Context())
			applyManualBaseline(baseline)
			applyProviderHeaders(req)
			if len(req.Header.Values("X-Stainless-Os")) != 1 || len(req.Header.Values("X-Stainless-Arch")) != 1 {
				t.Fatal("duplicate platform headers")
			}
			for _, key := range []string{"User-Agent", "X-Stainless-Runtime", "X-Stainless-Runtime-Version", "X-Stainless-Lang", "X-Stainless-Package-Version", "X-App", "Anthropic-Dangerous-Direct-Browser-Access", "Anthropic-Version", "Accept", "Accept-Encoding"} {
				if req.Header.Get(key) != baseline.Header.Get(key) {
					t.Fatalf("manual field changed: %s", key)
				}
			}
			res, err := server.Client().Do(req)
			if err != nil {
				t.Fatal(err)
			}
			reply, _ := io.ReadAll(res.Body)
			res.Body.Close()
			h := <-received
			if h.Get("X-Stainless-Os") != wantOS || h.Get("X-Stainless-Arch") != wantArch {
				t.Fatal(h)
			}
			if h.Get("X-Timezone") != "Asia/Tokyo" || h.Get("Accept-Language") != "zh-CN" || <-payload != body {
				t.Fatal("timezone, locale, or customer body changed")
			}
			if string(reply) != "OK" {
				t.Fatal("response changed")
			}
			t.Logf("Captured actual HTTP headers: X-Stainless-OS=%s X-Stainless-Arch=%s; container=%s/%s", h.Get("X-Stainless-Os"), h.Get("X-Stainless-Arch"), system.String(), machine.String())
		})
	}
}

func TestOAuthHeadersRemainSeparate(t *testing.T) {
	for _, path := range []string{"/v1/oauth/token", "/api/oauth/profile", "/api/oauth/claude_cli/roles"} {
		req, _ := http.NewRequest("POST", "https://api.anthropic.com"+path, nil)
		req.Header.Set("X-Stainless-OS", "caller-os")
		req.Header.Set("X-Stainless-Arch", "caller-arch")
		applyProviderHeaders(req)
		if req.Header.Get("X-Stainless-OS") != "caller-os" || req.Header.Get("X-Stainless-Arch") != "caller-arch" || req.Header.Get("User-Agent") != "CLIProxyAPI/8.1.1 cpa-container-worker/control-recovery1" {
			t.Fatal("OAuth handling changed")
		}
	}
}

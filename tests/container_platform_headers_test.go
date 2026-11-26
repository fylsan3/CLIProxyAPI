package main

import (
	"io"
"os"
"encoding/json"
"crypto/sha256"
"encoding/hex"
	"net/http"
	"net/http/httptest"
"net/url"
"reflect"
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
 frozenPlatformOS, frozenPlatformArch = wantOS, wantArch
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
			req, _ := http.NewRequest("POST", "https://api.anthropic.com"+path, strings.NewReader(body))
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
			req.URL, _ = url.Parse(server.URL+path)
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

func TestOAuthFinalHeaderOwnership(t *testing.T) {
 for _,op:=range accountOperations {
  if op.Kind!="oauth" {continue}
  req,_:=http.NewRequest(op.Method,"https://"+op.Host+op.Path,nil)
  req.Header.Set("User-Agent","stale-upstream-layer")
  req.Header.Set("Authorization","Bearer fixture")
  req.Header.Set("Cache-Control","no-store");req.Close=true
  applyProviderHeaders(req)
  expected:=http.Header{"Accept":[]string{"application/json, text/plain, */*"},"Accept-Encoding":[]string{"gzip, compress, deflate, br"},"Authorization":[]string{"Bearer fixture"},"User-Agent":[]string{"axios/1.15.2"},"Content-Type":[]string{"application/json"},"Connection":[]string{"keep-alive"}}
  switch op.Path {
  case "/api/oauth/profile":expected.Set("User-Agent","claude-code/2.1.331");expected.Set("Cache-Control","no-cache")
  case "/api/oauth/claude_cli/roles":expected.Set("User-Agent","claude-code/2.1.331");expected.Del("Content-Type")
  case "/api/oauth/usage":expected.Set("User-Agent","claude-cli/2.1.331 (external, sdk-cli)");expected.Set("Anthropic-Beta","oauth-2025-04-20")
  }
  if !reflect.DeepEqual(expected,req.Header)||req.Close {t.Fatal("final OAuth policy mismatch",op.Path,req.Header)}
 }
}

func TestBaselineRestorationAndMismatch(t *testing.T) {
 b,err:=os.ReadFile("/etc/os-release");if err!=nil { t.Fatal(err) }; sum:=sha256.Sum256(b)
 record:=map[string]any{"runtime":map[string]any{"architecture":"aarch64","os_release_sha256":hex.EncodeToString(sum[:])}}
 write:=func(){ raw,_:=json.Marshal(record);if err:=os.WriteFile("/state/retention.json",raw,0600);err!=nil { t.Fatal(err) } }
 write();if err:=loadContainerPlatformBaseline();err!=nil {t.Fatal(err)}
 firstOS,firstArch:=containerPlatformHeaders();frozenPlatformOS="";frozenPlatformArch=""
 if err:=loadContainerPlatformBaseline();err!=nil {t.Fatal(err)}
 if frozenPlatformOS!=firstOS || frozenPlatformArch!=firstArch {t.Fatal("restored baseline changed")}
 record["runtime"].(map[string]any)["architecture"]="x86_64";write()
 if loadContainerPlatformBaseline()==nil {t.Fatal("architecture mismatch accepted")}
 record["runtime"].(map[string]any)["architecture"]="aarch64";record["runtime"].(map[string]any)["os_release_sha256"]="wrong";write()
 if loadContainerPlatformBaseline()==nil {t.Fatal("OS mismatch accepted")}
}

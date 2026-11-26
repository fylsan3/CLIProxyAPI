package util

import (
 "net/http"
 "testing"
 "time"
)

func TestContainerCooldownDeadlineAndScope(t *testing.T) {
 now := time.Date(2026, 11, 26, 0, 0, 0, 0, time.UTC)
 until := now.Add(90*time.Second)
 h := http.Header{}
 h.Set(ContainerCooldownBridge, "1")
 h.Set(ContainerRetryAt, until.Format(time.RFC3339Nano))
 h.Set(ContainerCredentialScope, "true")
 h.Set(ContainerTransientRateLimit, "true")
 h.Set("Retry-After", "9999")
 got := ReadContainerCooldownHint(h, now.Add(10*time.Second))
 if !got.RetryAt.Equal(until) || !got.CredentialScoped || got.TransientRateLimit {
  t.Fatalf("native deadline or scope changed: %+v", got)
 }
 if h.Get("Retry-After") != "9999" { t.Fatal("original response changed") }
}

func TestContainerCooldownLegacyHeaders(t *testing.T) {
 now := time.Date(2026, 11, 26, 0, 0, 0, 0, time.UTC)
 for _, tc := range []struct {name,value string; want time.Time}{
  {"Retry-After", "120", now.Add(2*time.Minute)},
  {"Retry-After-Ms", "1500", now.Add(1500*time.Millisecond)},
  {"Retry-After", now.Add(time.Hour).Format(http.TimeFormat), now.Add(time.Hour)},
  {"Retry-After", "NaN", time.Time{}},
  {"Retry-After", "+Inf", time.Time{}},
  {"Retry-After", "-2", time.Time{}},
  {"Retry-After", "1e100", time.Time{}},
 } {
  h:=http.Header{};h.Set(tc.name,tc.value)
  got:=ReadContainerCooldownHint(h,now)
  if !got.RetryAt.Equal(tc.want) || got.CredentialScoped || got.TransientRateLimit { t.Fatalf("%s: %+v",tc.value,got) }
 }
}

func TestContainerCooldownPrivateBoundary(t *testing.T) {
 h:=http.Header{"Retry-After": {"120"}, "Anthropic-Beta":{"keep"}}
 for _,n:=range []string{ContainerCooldownBridge,ContainerRetryAt,ContainerCredentialScope,ContainerTransientRateLimit} { h.Set(n,"private") }
 for _,filter:=range []func(http.Header)http.Header{ContainerRequestHeaders,ContainerResponseHeaders} {
  got:=filter(h)
  for _,n:=range []string{ContainerCooldownBridge,ContainerRetryAt,ContainerCredentialScope,ContainerTransientRateLimit} { if got.Get(n)!="" { t.Fatal("private receipt escaped",n) } }
  if got.Get("Retry-After")!="120" || got.Get("Anthropic-Beta")!="keep" { t.Fatal("public protocol headers changed") }
 }
}

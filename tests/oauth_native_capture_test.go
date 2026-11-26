//go:build cpa_offline

package main

import (
 "context"
 "crypto/ecdsa"
 "crypto/elliptic"
 "crypto/rand"
 "crypto/sha256"
 "crypto/tls"
 "crypto/x509"
 "encoding/hex"
 "encoding/json"
 "io"
 "math/big"
 "net"
 "net/http"
 "net/http/httptest"
 "os"
 "strings"
 "sync"
 "testing"
 "time"

 claudeauth "github.com/router-for-me/CLIProxyAPI/v8/internal/auth/claude"
 "github.com/router-for-me/CLIProxyAPI/v8/internal/buildinfo"
 "github.com/router-for-me/CLIProxyAPI/v8/internal/config"
 native "github.com/router-for-me/CLIProxyAPI/v8/internal/runtime/executor"
 coreauth "github.com/router-for-me/CLIProxyAPI/v8/sdk/cliproxy/auth"
 execution "github.com/router-for-me/CLIProxyAPI/v8/sdk/cliproxy/executor"
 translator "github.com/router-for-me/CLIProxyAPI/v8/sdk/translator"
)

type oauthWireRecord struct {
 Method string `json:"method"`
 Host string `json:"host"`
 Path string `json:"path"`
 Headers http.Header `json:"headers"`
 BodyHash string `json:"body_sha256"`
 Grant string `json:"grant_type,omitempty"`
 Close bool `json:"connection_close"`
}

func TestNativeOAuthFinalWireCapture(t *testing.T) {
 var mu sync.Mutex;records:=[]oauthWireRecord{}
 handler:=http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){
  raw,_:=io.ReadAll(r.Body);sum:=sha256.Sum256(raw)
  var body map[string]any;_ = json.Unmarshal(raw,&body)
  grant,_:=body["grant_type"].(string)
  row:=oauthWireRecord{r.Method,r.Host,r.URL.RequestURI(),r.Header.Clone(),hex.EncodeToString(sum[:]),grant,r.Close}
  mu.Lock();records=append(records,row);mu.Unlock()
  w.Header().Set("Content-Type","application/json")
  switch r.URL.Path {
  case "/v1/oauth/token":io.WriteString(w,`{"access_token":"fixture-access","refresh_token":"fixture-refresh","expires_in":28800,"account":{"uuid":"fixture-account","email_address":"fixture@example.invalid"},"organization":{"uuid":"fixture-org","name":"Fixture"}}`)
  case "/api/oauth/profile":io.WriteString(w,`{"account":{"uuid":"fixture-account","email":"fixture@example.invalid"},"organization":{"uuid":"fixture-org","name":"Fixture"}}`)
  case "/api/oauth/claude_cli/roles":io.WriteString(w,`{"organization_role":"member"}`)
  case "/api/oauth/usage":io.WriteString(w,`{"five_hour":{"utilization":17},"cedar_ember":{"grants":[{"resets_left":2}]}}`)
  case "/v1/messages/count_tokens":io.WriteString(w,`{"input_tokens":3}`)
  default:io.WriteString(w,`{"id":"fixture-message","type":"message","role":"assistant","model":"claude-opus-4-6","content":[{"type":"text","text":"OK"}],"stop_reason":"end_turn","usage":{"input_tokens":1,"output_tokens":1}}`)
  }
 })
 server:=httptest.NewUnstartedServer(handler)
 key,err:=ecdsa.GenerateKey(elliptic.P256(),rand.Reader);if err!=nil{t.Fatal(err)}
 template:=&x509.Certificate{SerialNumber:big.NewInt(42),DNSNames:[]string{"api.anthropic.com","platform.claude.com"},NotBefore:time.Now().Add(-time.Minute),NotAfter:time.Now().Add(time.Hour),KeyUsage:x509.KeyUsageDigitalSignature|x509.KeyUsageCertSign,ExtKeyUsage:[]x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},IsCA:true,BasicConstraintsValid:true}
 der,err:=x509.CreateCertificate(rand.Reader,template,template,&key.PublicKey,key);if err!=nil{t.Fatal(err)}
 certificate,_:=x509.ParseCertificate(der);roots:=x509.NewCertPool();roots.AddCert(certificate)
 server.TLS=&tls.Config{Certificates:[]tls.Certificate{{Certificate:[][]byte{der},PrivateKey:key}}};server.StartTLS();defer server.Close()
 base:=&http.Transport{TLSClientConfig:&tls.Config{RootCAs:roots},DialContext:func(ctx context.Context,_,address string)(net.Conn,error){
  if address!="api.anthropic.com:443"&&address!="platform.claude.com:443"{t.Errorf("unexpected destination %s",address)}
  return (&net.Dialer{}).DialContext(ctx,"tcp",server.Listener.Addr().String())
 }};defer base.CloseIdleConnections()
 final:=&providerTransport{base:base,owner:"A",provider:"claude-subscription"}
 take:=func()[]oauthWireRecord{mu.Lock();defer mu.Unlock();v:=append([]oauthWireRecord(nil),records...);records=nil;return v}
 exercise:=func(rt http.RoundTripper)[]oauthWireRecord{
  service:=claudeauth.NewContainerAuth(&http.Client{Transport:rt})
  pkce,err:=claudeauth.GeneratePKCECodes();if err!=nil{t.Fatal(err)}
  // Deterministic fictional PKCE only; never saved to an account volume.
  pkce.CodeVerifier="fictional-verifier";pkce.CodeChallenge="fictional-challenge"
  if _,err=service.ExchangeCodeForTokens(context.Background(),"fictional-code","fictional-state",pkce);err!=nil{t.Fatal(err)}
  if _,err=service.RefreshTokens(context.Background(),"fixture-refresh");err!=nil{t.Fatal(err)}
  for _,kind:=range []string{"profile","usage"}{if _,err=service.FetchContainerAccountResource(context.Background(),"fixture-access",kind);err!=nil{t.Fatal(err)}}
  return take()
 }
 current:=exercise(final)
 for _,row:=range current{
  path:=strings.SplitN(row.Path,"?",2)[0]
  expectedUA:="axios/1.15.2"
  if path=="/api/oauth/profile"||path=="/api/oauth/claude_cli/roles"{expectedUA="claude-code/2.1.331"}
  if path=="/api/oauth/usage"{expectedUA="claude-cli/2.1.331 (external, sdk-cli)"}
  if row.Headers.Get("User-Agent")!=expectedUA||row.Close||row.Headers.Get("Connection")!="keep-alive"{t.Fatal("user source headers not active",row)}
  if strings.HasPrefix(path,"/api/oauth/")&&row.Headers.Get("Authorization")!="Bearer fixture-access"{t.Fatal("wrong account credential",row)}
  cache:="";if path=="/api/oauth/profile"{cache="no-cache"}
  if row.Headers.Get("Cache-Control")!=cache{t.Fatal("cache header mismatch",row)}
  ct:="application/json";if path=="/api/oauth/claude_cli/roles"{ct=""}
  if row.Headers.Get("Content-Type")!=ct{t.Fatal("content type mismatch",row)}
  for name,values:=range row.Headers{if strings.HasPrefix(strings.ToLower(name),"x-stainless-")||strings.Contains(strings.Join(values," "),"control-recovery1"){t.Fatal("unexpected OAuth override",name)}}
 }
 // Real native executor fallback, without the account's final manual overrides.
 priorVersion:=buildinfo.Version;buildinfo.Version="8.1.1";defer func(){buildinfo.Version=priorVersion}()
 fallbackServer:=httptest.NewServer(handler);defer fallbackServer.Close()
 auth:=&coreauth.Auth{ID:"fixture-fallback",Attributes:map[string]string{"api_key":"fixture-api-key","base_url":fallbackServer.URL}}
 executor:=native.NewClaudeExecutor(&config.Config{})
 payload:=[]byte(`{"model":"claude-opus-4-6","messages":[{"role":"user","content":"fixture"}]}`)
 if _,err=executor.Execute(context.Background(),auth,execution.Request{Model:"claude-opus-4-6",Payload:payload},execution.Options{SourceFormat:translator.FormatClaude});err!=nil{t.Fatal(err)}
 fallback:=take();if len(fallback)!=1||fallback[0].Headers.Get("User-Agent")!="CLIProxyAPI/8.1.1"{t.Fatal("native fallback changed",fallback)}
 frozenPlatformOS,frozenPlatformArch="Linux","arm64"
 client:=&http.Client{Transport:final}
 for _,path:=range []string{"/v1/messages","/v1/messages/count_tokens"}{
  req,_:=http.NewRequest("POST","https://api.anthropic.com"+path,strings.NewReader(string(payload)))
  req.Header=fallback[0].Headers.Clone();req.Header.Del("Content-Length");req.Header.Set("Authorization","Bearer fixture-access")
  res,err:=client.Do(req);if err!=nil{t.Fatal(err)};io.Copy(io.Discard,res.Body);res.Body.Close()
 }
 model:=take();if len(model)!=2{t.Fatal(model)}
 for _,row:=range model{for k,v:=range modelHeaderOverrides(){if row.Headers.Get(k)!=v{t.Fatal("manual override changed",k,row)}};if row.BodyHash!=hex.EncodeToString(sha256sum(payload)){t.Fatal("body changed")}}
 report:=map[string]any{"real_accounts_used":false,"network":"Docker network none, loopback HTTPS fixture only","policy_single_source":true,"oauth_requests":current,"native_model_fallback":fallback,"final_model_requests":model,"coverage":"native OAuth methods plus actual providerTransport; not full broker/container boot or official upstream"}
 raw,_:=json.MarshalIndent(report,"","  ");if err=os.WriteFile("/tmp/oauth-native-capture.json",raw,0600);err!=nil{t.Fatal(err)}
 t.Logf("Captured %d OAuth requests, native fallback and %d final model requests; headers assigned at final transport",len(current),len(model))
}
func sha256sum(b []byte)[]byte{s:=sha256.Sum256(b);return s[:]}

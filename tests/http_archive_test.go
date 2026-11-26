package main

import (
 "bytes"
 "context"
 "compress/gzip"
 "crypto/cipher"
 "encoding/binary"
 "encoding/json"
 "io"
 "net/http"
 "net/http/httptest"
 "os"
 "path/filepath"
 "strings"
 "testing"
)

func decryptTest(t *testing.T,aead cipher.AEAD,path string) []byte {
 t.Helper();raw,err:=os.ReadFile(path);if err!=nil{t.Fatal(err)}
 if !bytes.HasPrefix(raw,[]byte("CPAENC1\n")){t.Fatal("magic")};raw=raw[8:];var out []byte;ended:=false
 for len(raw)>0 {if len(raw)<4||ended{t.Fatal("trailing or short data")};n:=int(binary.BigEndian.Uint32(raw));raw=raw[4:];if len(raw)<n||n<28{t.Fatal("length")};v,err:=aead.Open(nil,raw[:12],raw[12:n],[]byte(filepath.Base(path)));if err!=nil{t.Fatal(err)};raw=raw[n:];if len(v)==0{ended=true}else{out=append(out,v...)}}
 if !ended{t.Fatal("missing final record")};return out
}
func readMeta(t *testing.T,a *httpArchive,dir,name string) map[string]any {t.Helper();var v map[string]any;if err:=json.Unmarshal(decryptTest(t,a.aead,filepath.Join(dir,name)),&v);err!=nil{t.Fatal(err)};return v}

func TestHTTPArchiveRetainsAllHeadersAndBodies(t *testing.T){
 root:=t.TempDir();a,err:=newHTTPArchive(root,"test");if err!=nil{t.Fatal(err)}
 var received http.Header
 reply:=[]byte("event: message\r\ndata: {\"secret\":\"response-body-canary\"}\r\n\r\n")
 srv:=httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){received=r.Header.Clone();received.Set("Host",r.Host);if r.URL.RawQuery!="cedar_ember=1&skip_spend=1"{t.Error("query lost")};body,_:=io.ReadAll(r.Body);if string(body)!="request-body-canary"{t.Error("body changed")};w.Header().Add("Set-Cookie","secret-cookie-canary");w.Header().Add("X-Repeated","first");w.Header().Add("X-Repeated","second");w.Header().Set("Trailer","X-Ending");w.WriteHeader(403);w.Write(reply);w.(http.Flusher).Flush();w.Header().Set("X-Ending","tail-value")}));defer srv.Close()
 req,_:=http.NewRequest("POST",srv.URL+"/v1/messages?cedar_ember=1&skip_spend=1",strings.NewReader("request-body-canary"));req.Header.Set("Authorization","Bearer secret-auth-canary");req.Header.Set("Cookie","request-cookie-canary");req.Header.Add("X-Extra","a");req.Header.Add("X-Extra","b");req.Close=true
 res,err:=a.send(req,http.DefaultTransport.RoundTrip);if err!=nil{t.Fatal(err)};got,err:=io.ReadAll(res.Body);res.Body.Close();if err!=nil||!bytes.Equal(got,reply){t.Fatal("live response changed",err)}
 if a.status()["state"]!="complete"{t.Fatal(a.status())};dir:=filepath.Join(a.dir,"0001");q:=readMeta(t,a,dir,"request.json.enc");r:=readMeta(t,a,dir,"response.json.enc")
 wire:=http.Header{};for _,v:=range q["wire_headers"].([]any){entry:=v.(map[string]any);for _,value:=range entry["values"].([]any){wire.Add(entry["name"].(string),value.(string))}}
 for name,values:=range received {if strings.Join(wire.Values(name),"|")!=strings.Join(values,"|"){t.Fatalf("header mismatch %s",name)}}
 if wire.Get("User-Agent")==""||wire.Get("Host")==""||wire.Get("Content-Length")==""{t.Fatal("transport headers missing")}
 if wire.Get("Authorization")!="Bearer secret-auth-canary"{t.Fatal("authorization removed from encrypted original")}
 if !bytes.Equal(decryptTest(t,a.aead,filepath.Join(dir,"request.bin.enc")),[]byte("request-body-canary"))||!bytes.Equal(decryptTest(t,a.aead,filepath.Join(dir,"response.bin.enc")),reply){t.Fatal("archived body changed")}
 if r["status"]!=float64(403)||r["trailers"].(map[string]any)["X-Ending"].([]any)[0]!="tail-value"{t.Fatal("response status or trailer lost")}
 filepath.Walk(a.dir,func(path string,info os.FileInfo,err error)error{if err==nil&&!info.IsDir(){data,_:=os.ReadFile(path);for _,canary:=range []string{"secret-auth-canary","secret-cookie-canary","request-body-canary","response-body-canary"}{if bytes.Contains(data,[]byte(canary)){t.Fatal("plaintext persisted")}};if info.Mode().Perm()!=0600{t.Fatal("not private")}};return err})
 if export:=os.Getenv("ARCHIVE_TEST_EXPORT");export!="" {var copyDir func(string,string);copyDir=func(src,dst string){os.MkdirAll(dst,0700);entries,_:=os.ReadDir(src);for _,e:=range entries{if e.IsDir(){copyDir(filepath.Join(src,e.Name()),filepath.Join(dst,e.Name()))}else{b,_:=os.ReadFile(filepath.Join(src,e.Name()));os.WriteFile(filepath.Join(dst,e.Name()),b,0600)}}};copyDir(root,export)}
}
func TestHTTPArchiveGETEmptyBodyAndPartialReply(t *testing.T){
 a,err:=newHTTPArchive(t.TempDir(),"usage");if err!=nil{t.Fatal(err)}
 srv:=httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){w.Header().Set("Content-Length","100");w.WriteHeader(200);w.Write([]byte("short"))}));defer srv.Close()
 req,_:=http.NewRequest("GET",srv.URL+"/usage",nil);res,err:=a.send(req,http.DefaultTransport.RoundTrip);if err!=nil{t.Fatal(err)};_,_=io.ReadAll(res.Body);res.Body.Close()
 if a.status()["state"]!="incomplete"{t.Fatal(a.status())};q:=readMeta(t,a,filepath.Join(a.dir,"0001"),"request.json.enc");if q["complete"]!=true||q["bytes"]!=float64(0){t.Fatal("GET empty body must be complete")}
}
func TestHTTPArchiveCancellationAndStorageFailureDoNotClaimSuccess(t *testing.T){
 a,err:=newHTTPArchive(t.TempDir(),"test");if err!=nil{t.Fatal(err)};ctx,cancel:=context.WithCancel(context.Background());cancel();req,_:=http.NewRequestWithContext(ctx,"GET","http://127.0.0.1:1/",nil);_,err=a.send(req,http.DefaultTransport.RoundTrip);if err==nil||a.status()["state"]!="incomplete"{t.Fatal("cancelled request claimed complete")}
 b,err:=newHTTPArchive(t.TempDir(),"test");if err!=nil{t.Fatal(err)};os.RemoveAll(b.dir);os.WriteFile(b.dir,[]byte("blocked"),0600);req,_=http.NewRequest("GET","http://unused/",nil);called:=false;res,err:=b.send(req,func(*http.Request)(*http.Response,error){called=true;return &http.Response{StatusCode:200,Body:http.NoBody},nil});if err!=nil||!called||res.StatusCode!=200||b.status()["state"]!="incomplete"{t.Fatal("capture failure changed live operation")}
}

func TestHTTPArchiveChunkedUploadAndCompressedReply(t *testing.T){
 a,err:=newHTTPArchive(t.TempDir(),"test");if err!=nil{t.Fatal(err)}
 var zipped bytes.Buffer;z:=gzip.NewWriter(&zipped);z.Write([]byte("exact encoded response"));z.Close()
 srv:=httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){v,_:=io.ReadAll(r.Body);if string(v)!="unknown length upload"{t.Error("upload changed")};w.Header().Set("Content-Encoding","gzip");w.Write(zipped.Bytes())}));defer srv.Close()
 req,_:=http.NewRequest("POST",srv.URL,io.NopCloser(strings.NewReader("unknown length upload")));req.Header.Set("Accept-Encoding","gzip")
 res,err:=a.send(req,http.DefaultTransport.RoundTrip);if err!=nil{t.Fatal(err)};got,err:=io.ReadAll(res.Body);res.Body.Close();if err!=nil||!bytes.Equal(got,zipped.Bytes()){t.Fatal("encoded reply changed")}
 if a.status()["state"]!="complete"{t.Fatal(a.status())};dir:=filepath.Join(a.dir,"0001");q:=readMeta(t,a,dir,"request.json.enc");if q["transfer_encoding"].([]any)[0]!="chunked"{t.Fatal("wire framing missing")};if !bytes.Equal(decryptTest(t,a.aead,filepath.Join(dir,"response.bin.enc")),zipped.Bytes()){t.Fatal("compressed bytes lost")}
}

func TestCaptureWindowAndHeaderAlarms(t *testing.T) {
 root:=t.TempDir()
 if captureWindowActive(root){t.Fatal("captured without opt in")}
 p:=filepath.Join(root,"capture-window.json")
 os.WriteFile(p,[]byte(`{"enabled":true,"expires":4102444800}`),0600)
 if !captureWindowActive(root){t.Fatal("window not active")}
 os.WriteFile(p,[]byte(`{"enabled":true,"expires":1}`),0600)
 if captureWindowActive(root){t.Fatal("expired window active")}
 h:=modelHeaderOverrides();wire:=[]map[string]any{}
 for k,v:=range h{wire=append(wire,map[string]any{"name":k,"values":[]string{v}})}
 wire=append(wire,map[string]any{"name":"Authorization","values":[]string{"Bearer do-not-export-canary"}})
 bad,unknown:=auditHeaderNames("/v1/messages",wire);if len(bad)+len(unknown)!=0{t.Fatal(bad,unknown)}
 wire=append(wire,map[string]any{"name":"User-Agent","values":[]string{"unexpected-client-canary"}},map[string]any{"name":"X-Unknown","values":[]string{"secret-extra-canary"}})
 recordHeaderAudit(root,"sample","/v1/messages",wire,true)
 b,_:=os.ReadFile(filepath.Join(root,"header-audit.json"))
 for _,secret:=range []string{"do-not-export-canary","unexpected-client-canary","secret-extra-canary"}{if bytes.Contains(b,[]byte(secret)){t.Fatal("audit leaked value")}}
 var v map[string]any;json.Unmarshal(b,&v);if len(v["alerts"].([]any))!=1{t.Fatal("missing alert")}
 if !bytes.Contains(b,[]byte("user-agent"))||!bytes.Contains(b,[]byte("x-unknown")){t.Fatal("missing field names")}
}

// Deliberately corrupt emitted observations: the monitor must not merely report
// success because the sender and monitor share the same policy source.
func TestUnifiedOAuthWireAudit(t *testing.T) {
 for _,op:=range accountOperations {
  req,_:=http.NewRequest(op.Method,"https://"+op.Host+op.Path,nil)
  req.Header.Set("Authorization","Bearer fake-account-A")
  applyProviderHeaders(req)
  wire:=[]map[string]any{}
  for k,v:=range req.Header {wire=append(wire,map[string]any{"name":k,"values":v})}
  mismatch,unknown:=auditHeaderNames(op.Path,wire)
  if len(mismatch)>0||len(unknown)>0{t.Fatalf("valid %s: %v %v",op.Path,mismatch,unknown)}
  wire=append(wire,map[string]any{"name":"user-agent","values":[]string{"wrong-agent"}})
  mismatch,_=auditHeaderNames(op.Path,wire)
  if len(mismatch)==0{t.Fatal("duplicate/conflicting UA not detected",op.Path)}
 }
 bad:=[]map[string]any{{"name":"X-Unreviewed","values":[]string{"SECRET_CANARY"}}}
 _,unknown:=auditHeaderNames("/api/oauth/profile",bad)
 if len(unknown)!=1||unknown[0]!="x-unreviewed"{t.Fatal("unknown header not reported",unknown)}
 req,_:=http.NewRequest("GET","https://api.anthropic.com/api/oauth/claude_cli/roles",nil);applyProviderHeaders(req)
 wire:=[]map[string]any{}
 for k,v:=range req.Header {wire=append(wire,map[string]any{"name":k,"values":v})}
 wire=append(wire,map[string]any{"name":"Content-Type","values":[]string{"application/json"}})
 mismatch,_:=auditHeaderNames(req.URL.Path,wire)
 if len(mismatch)!=1||mismatch[0]!="content-type"{t.Fatal("roles forbidden header undetected",mismatch)}
}

func TestHTTPArchiveBeforeAndFinalPolicySnapshots(t *testing.T) {
 root:=t.TempDir();a,err:=newHTTPArchive(root,"comparison");if err!=nil{t.Fatal(err)}
 srv:=httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){
  if r.Header.Get("User-Agent")!="claude-code/2.1.331"{t.Fatal("wrong wire UA")}
  w.Write([]byte(`{"ok":true}`))
 }));defer srv.Close()
 before,_:=http.NewRequest("GET","https://api.anthropic.com/api/oauth/profile",nil)
 before.Header.Set("Authorization","Bearer BEFORE_SECRET");before.Header.Set("User-Agent","prior-agent");before.Close=true
 final:=before.Clone(before.Context());applyProviderHeaders(final)
 final.URL.Scheme="http";final.URL.Host=strings.TrimPrefix(srv.URL,"http://")
 res,err:=a.sendCompared(final,before,http.DefaultTransport.RoundTrip);if err!=nil{t.Fatal(err)};io.Copy(io.Discard,res.Body);res.Body.Close()
 q:=readMeta(t,a,filepath.Join(a.dir,"0001"),"request.json.enc")
 pre:=q["before_override"].(map[string]any)
 if pre["headers"].(map[string]any)["User-Agent"].([]any)[0]!="prior-agent"||pre["close"]!=true||q["close"]!=false{t.Fatal("before snapshot lost")}
 if q["headers"].(map[string]any)["User-Agent"].([]any)[0]!="claude-code/2.1.331"{t.Fatal("after snapshot lost")}
 if before.Header.Get("User-Agent")!="prior-agent"||!before.Close{t.Fatal("caller request mutated")}
}

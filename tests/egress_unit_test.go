package main
import("context";"io";"net";"net/http";"net/http/httptest";"strings";"testing";"time";"encoding/binary";"encoding/json";"os";"path/filepath";"reflect")
func containerPlatformHeaders()(string,string){return "Linux","arm64"}
func TestAllAccountPolicies(t *testing.T){
 for _,op:=range accountOperations{
  r,_:=http.NewRequest(op.Method,"https://"+op.Host+op.Path,strings.NewReader("BODY_UNCHANGED"));r.Header.Set("Authorization","Bearer fictional");r.Header.Set("X-Unrelated","keep")
  r.Close=true;r.Header.Set("Cache-Control","no-cache");r.Header["cache-control"]=[]string{"no-store"}
  before:=r.Header.Clone();applyProviderHeaders(r)
  if op.Kind=="model"{for k,v:=range modelHeaderOverrides(){if r.Header.Get(k)!=v{t.Fatal(op.Path,k)}}}else if op.Path=="/api/oauth/usage"{
   if r.Close||r.Header.Get("User-Agent")!="claude-cli/2.1.331 (external, sdk-cli)"||r.Header.Get("Content-Type")!="application/json"||r.Header.Get("Connection")!="keep-alive"||r.Header.Get("Anthropic-Beta")!="oauth-2025-04-20"{t.Fatal("usage policy mismatch",r.Header)}
   for name:=range r.Header{if strings.EqualFold(name,"Cache-Control"){t.Fatal("usage cache header retained")}}
  }else if !reflect.DeepEqual(r.Header,before){t.Fatal("OAuth native headers changed",op)}
  body,_:=io.ReadAll(r.Body);if string(body)!="BODY_UNCHANGED"||r.Header.Get("Authorization")!="Bearer fictional"||r.Header.Get("X-Unrelated")!="keep"{t.Fatal("content/auth changed")}
  r.Method="DELETE";if _,ok:=accountOperationFor(r);ok{t.Fatal("invalid method admitted")}
 }
 r,_:=http.NewRequest("GET","https://evil.invalid/api/oauth/profile",nil);if _,ok:=accountOperationFor(r);ok{t.Fatal("unknown host")}
 r,_=http.NewRequest("GET","https://api.ipify.org/",nil);r.Header.Set("Authorization","must-not-leak");applyNetworkCheckHeaders(r,"exit");if r.Header.Get("Authorization")!=""||r.Header.Get("User-Agent")!="CPA-Network-Check/1"{t.Fatal("probe policy")}
}
// The fake authenticated SOCKS server runs on loopback only. It resolves no names.
func localProxy(t *testing.T, destination string)(net.Listener,<-chan string){
 t.Helper();l,err:=net.Listen("tcp","127.0.0.1:0");if err!=nil{t.Fatal(err)};t.Cleanup(func(){l.Close()});seen:=make(chan string,8)
 go func(){for{c,err:=l.Accept();if err!=nil{return};go func(){defer c.Close();c.SetDeadline(time.Now().Add(5*time.Second));h:=make([]byte,2);if _,err:=io.ReadFull(c,h);err!=nil{return};m:=make([]byte,int(h[1]));io.ReadFull(c,m);c.Write([]byte{5,2});io.ReadFull(c,h);u:=make([]byte,int(h[1]));io.ReadFull(c,u);one:=make([]byte,1);io.ReadFull(c,one);p:=make([]byte,int(one[0]));io.ReadFull(c,p);if string(u)!="fixture"||string(p)!="secret"{c.Write([]byte{1,1});return};c.Write([]byte{1,0});hdr:=make([]byte,3);io.ReadFull(c,hdr);address,err:=readSOCKSDestination(c);if err!=nil{return};seen<-address
 remote,err:=net.Dial("tcp",destination);if err!=nil{return};defer remote.Close();c.Write([]byte{5,0,0,1,0,0,0,0,0,0});c.SetDeadline(time.Time{});done:=make(chan struct{});go func(){io.Copy(remote,c);remote.(*net.TCPConn).CloseWrite();close(done)}();io.Copy(c,remote);c.(*net.TCPConn).CloseWrite();<-done}()}}();return l,seen
}
func TestNetworkProbeAndNoDirectFallback(t *testing.T){
 var observed http.Header
 s:=httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){observed=r.Header.Clone();w.Write([]byte(`{"ip":"203.0.113.10","success":true,"timezone":{"id":"Europe/London"}}`))}));defer s.Close()
 proxy,seen:=localProxy(t,strings.TrimPrefix(s.URL,"http://"));host,port,_:=net.SplitHostPort(proxy.Addr().String());var portInt int;json.Unmarshal([]byte(port),&portInt)
 n:=newAccountNetwork(accountNetworkConfig{Owner:"A",Provider:"mock-claude",TestOnly:true,ProxyIP:host,ProxyPort:portInt,Username:"fixture",Password:"secret",CheckHost:"a.upstream.invalid",CheckPort:8080})
 v,err:=n.location(context.Background());if err!=nil||v["timezone"]!="Europe/London"{t.Fatal(v,err)}
 if <-seen!="a.upstream.invalid:8080"||observed.Get("Authorization")!=""||observed.Get("User-Agent")!="CPA-Network-Check/1"{t.Fatal("probe escaped policy")}
 n.config.ExpectedEgress="203.0.113.11";if _,err=n.location(context.Background());err==nil{t.Fatal("wrong exit accepted")}
 proxy.Close();ctx,cancel:=context.WithTimeout(context.Background(),time.Second);defer cancel();if _,err=n.dial(ctx,strings.TrimPrefix(s.URL,"http://"));err==nil{t.Fatal("direct fallback")}
}
func TestSOCKSTunnelAndPolicy(t *testing.T){
 echo,_:=net.Listen("tcp","127.0.0.1:0");defer echo.Close();go func(){c,e:=echo.Accept();if e!=nil{return};defer c.Close();b,_:=io.ReadAll(c);c.Write(append([]byte("reply:"),b...))}()
 upstream,_:=localProxy(t,echo.Addr().String());host,p,_:=net.SplitHostPort(upstream.Addr().String());var port int;json.Unmarshal([]byte(p),&port)
 n:=newAccountNetwork(accountNetworkConfig{ProxyIP:host,ProxyPort:port,Username:"fixture",Password:"secret",TestOnly:true,CheckHost:"a.upstream.invalid",CheckPort:8080});n.healthy=true
 l,_:=net.Listen("tcp","127.0.0.1:0");defer l.Close();go func(){c,_:=l.Accept();n.handle(context.Background(),c)}();c,_:=net.Dial("tcp",l.Addr().String());defer c.Close();c.SetDeadline(time.Now().Add(5*time.Second));c.Write([]byte{5,1,0});h:=make([]byte,2);io.ReadFull(c,h);if h[1]!=0{t.Fatal("greeting")};name:=[]byte("a.upstream.invalid");packet:=append([]byte{5,1,0,3,byte(len(name))},name...);packet=binary.BigEndian.AppendUint16(packet,8080);c.Write(packet);response:=make([]byte,10);io.ReadFull(c,response);if response[1]!=0{t.Fatal("connect")};c.Write([]byte("body"));c.(*net.TCPConn).CloseWrite();b,err:=io.ReadAll(c);if err!=nil||string(b)!="reply:body"{t.Fatal(string(b),err)}
 n.config.TestOnly=false;for _,d:=range []string{"127.0.0.1:443","localhost:443","api.anthropic.com:53"}{if n.allowedDestination(d){t.Fatal(d)}}
 if !n.allowedDestination("api.anthropic.com:443"){t.Fatal("https denied")}
}
func TestStatusPublicButNotWritable(t *testing.T){
 n:=newAccountNetwork(accountNetworkConfig{Owner:"A"});dir:=t.TempDir();if err:=n.publish(dir);err!=nil{t.Fatal(err)};i,_:=os.Stat(filepath.Join(dir,"status.json"));if i.Mode().Perm()!=0644{t.Fatal(i.Mode())};b,_:=os.ReadFile(filepath.Join(dir,"status.json"));if strings.Contains(string(b),"secret")||!strings.Contains(string(b),`"egress_manager":"go"`){t.Fatal("status")}
}

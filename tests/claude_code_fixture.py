"""Closed-network test entrypoint; never installed as the account entrypoint."""
import http.server,json,os,signal,socketserver,subprocess,threading,time,ssl
from pathlib import Path
from datetime import datetime,timezone

owner=os.environ['FIXTURE_OWNER'];running=True
for name,uid,mode in [('/state',1001,0o700),('/run/network',0,0o755),('/run/network/live',1002,0o755)]:
 p=Path(name);p.mkdir(exist_ok=True,parents=True);p.chmod(mode);os.chown(p,uid,uid)
def save(p,value,uid):
 p=Path(p);t=p.with_suffix('.new');t.write_text(json.dumps(value));t.chmod(0o644);os.chown(t,uid,uid);os.replace(t,p)
save('/run/network/firewall.json',{'config_sha256':'claude-test','egress_manager':'go','egress_uid':1002},0)
if not Path('/state/native-auth.json').exists():
 save('/state/native-auth.json',{'owner':owner,'revision':1,'token':{'access_token':'sk-ant-oat01-offline-'+owner+'-1','refresh_token':'offline-refresh-'+owner+'-1','expired':datetime.fromtimestamp(time.time()+14400,timezone.utc).isoformat()}},1001)
 Path('/state/native-auth.json').chmod(0o600)
def heartbeat():
 while running:
  save('/run/network/live/status.json',{'owner':owner,'healthy':not Path('/tmp/proxy-failed').exists(),'checked_at':time.time()},1002);time.sleep(.2)
threading.Thread(target=heartbeat,daemon=True).start()

class Mock(http.server.BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_POST(self):
  b=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  current=json.loads(Path('/state/native-auth.json').read_text())
  matches=self.headers.get('Authorization')=='Bearer '+current['token']['access_token']
  with Path('/tmp/auth-observations.jsonl').open('a') as events:events.write(json.dumps({'path':self.path.split('?')[0],'authorization_matches_go':matches,'revision':current['revision']})+'\n')
  if not matches:
   raw=b'{"error":{"type":"authentication_error","message":"fixture token mismatch"}}';self.send_response(401);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
  text='OK';model=b.get('model','claude-sonnet-4-6')
  message={'id':'msg_'+owner,'type':'message','role':'assistant','model':model,'content':[],'stop_reason':None,'stop_sequence':None,'usage':{'input_tokens':10,'output_tokens':1}}
  events=[('message_start',{'message':message}),('content_block_start',{'index':0,'content_block':{'type':'text','text':''}}),('content_block_delta',{'index':0,'delta':{'type':'text_delta','text':text}}),('content_block_stop',{'index':0}),('message_delta',{'delta':{'stop_reason':'end_turn','stop_sequence':None},'usage':{'output_tokens':1}}),('message_stop',{})]
  raw=''.join('event: '+n+'\ndata: '+json.dumps(dict(v,type=n))+'\n\n' for n,v in events).encode()
  self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(raw)));self.end_headers()
  delay=Path('/tmp/model-delay');time.sleep(float(delay.read_text()) if delay.exists() else 2)
  try:self.wfile.write(raw)
  except BrokenPipeError:pass
server=http.server.ThreadingHTTPServer(('127.0.0.1',24800),Mock);threading.Thread(target=server.serve_forever,daemon=True).start()

# CLI interactive startup has its own HTTPS connectivity probe. Terminate it
# only inside this network-none fixture, with an explicitly trusted test CA.
class Preflight(Mock):
 def do_GET(self):
  raw=b'{}';self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
 def do_HEAD(self):self.send_response(200);self.end_headers()
class Socks(socketserver.BaseRequestHandler):
 def handle(self):
  s=self.request
  def exact(n):
   data=b''
   while len(data)<n:
    b=s.recv(n-len(data))
    if not b:raise OSError('closed')
    data+=b
   return data
  try:
   assert exact(3)==b'\x05\x01\x00';s.sendall(b'\x05\x00');head=exact(4);assert head==b'\x05\x01\x00\x03'
   host=exact(exact(1)[0]).decode();port=int.from_bytes(exact(2),'big')
   assert port==443 and host in ('api.anthropic.com','claude.ai','platform.claude.com')
   s.sendall(b'\x05\x00\x00\x01\x7f\x00\x00\x01\x01\xbb')
   ctx=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER);ctx.load_cert_chain('/bench/test-ca.crt','/bench/test-ca.key')
   with ctx.wrap_socket(s,server_side=True) as tls:Preflight(tls,self.client_address,self.server)
  except (OSError,AssertionError):pass
socks=socketserver.ThreadingTCPServer(('127.0.0.1',1080),Socks);socks.daemon_threads=True
threading.Thread(target=socks.serve_forever,daemon=True).start()

class Browser(socketserver.StreamRequestHandler):
 def handle(self):
  from urllib.parse import urlsplit
  v=json.loads(self.rfile.readline());u=urlsplit(v.get('url',''));Path('/tmp/browser-fixture-event.json').write_text(json.dumps({'op':v.get('op'),'host':u.hostname,'path':u.path,'valid_authorize_url':(u.hostname,u.path) in {('claude.ai','/oauth/authorize'),('platform.claude.com','/oauth/authorize'),('claude.com','/cai/oauth/authorize')}}))
  self.wfile.write(b'{"ok":true}\n')
Path('/tmp/fixture-control.sock').unlink(missing_ok=True)
browser=socketserver.ThreadingUnixStreamServer('/tmp/fixture-control.sock',Browser);os.chown('/tmp/fixture-control.sock',1001,1001);os.chmod('/tmp/fixture-control.sock',0o600)
threading.Thread(target=browser.serve_forever,daemon=True).start()
def identity():os.setgroups([]);os.setgid(1001);os.setuid(1001)
env=dict(os.environ,PROXY_CONFIG_SHA256='claude-test',CPA_PROVIDER='mock-claude',CLAUDE_CODE_LOCAL_TEST='1',CLAUDE_CODE_TEST_BASE_URL='http://127.0.0.1:24800',TZ='Asia/Tokyo')
p=subprocess.Popen(['python3','-B','/opt/native/claude_code.py','serve'],env=env,preexec_fn=identity)
def stop(*a):
 global running
 running=False;p.terminate()
signal.signal(signal.SIGTERM,stop)
while running and p.poll() is None:time.sleep(.2)
if p.poll() is None:p.terminate()
p.wait(timeout=10)

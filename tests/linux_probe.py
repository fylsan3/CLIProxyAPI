"""Run only inside a disposable Linux container, with no host Docker socket."""
import ctypes,errno,http.client,http.server,json,os,socket,socketserver,subprocess,sys,threading,time
from pathlib import Path
from network_guard import enforce
root=Path('/tmp/linux-proof');root.mkdir(mode=0o755);os.chmod(root,0o755)
private=root/'broker-private';private.mkdir(mode=0o700);os.chown(private,21001,21001);(private/'credential-canary').write_text('fictional-only')
control=root/'control';control.mkdir(mode=0o750);os.chown(control,21001,21002)
central=root/'central';central.mkdir(mode=0o700);os.chown(central,21003,21003)
trap=socket.socket(socket.AF_UNIX);trap.bind(str(root/'docker.sock'));os.chmod(root/'docker.sock',0o660);trap.listen(1)
allowed=socket.socket(socket.AF_UNIX);allowed.bind(str(control/'test.sock'));os.chmod(control/'test.sock',0o660);os.chown(control/'test.sock',21001,21002);allowed.listen(1)
read,write=os.pipe();pid=os.fork()
if pid==0:
 os.close(read);os.setgroups([21002]);os.setgid(21003);os.setuid(21003)
 result={}
 try:
  result.update(enforce())
  for label,family,address in [('tcp_loopback',socket.AF_INET,('127.0.0.1',9)),('tcp_external',socket.AF_INET,('198.18.0.1',443))]:
   try:
    with socket.socket(family) as s:s.connect(address)
    result[label]=False
   except OSError as e:result[label]=e.errno in (errno.EACCES,errno.EPERM)
  for label,kind in [('udp',socket.SOCK_DGRAM),('raw',socket.SOCK_RAW)]:
   try:socket.socket(socket.AF_INET,kind);result[label]=False
   except OSError as e:result[label]=e.errno in (errno.EACCES,errno.EPERM)
  with socket.socket(socket.AF_UNIX) as s:s.connect(str(control/'test.sock'));result['unix_allowed']=True
  with socket.socket() as s:s.bind(('127.0.0.1',0));s.listen(1);result['tcp_listen_allowed']=True
  try:(private/'credential-canary').read_bytes();result['private_denied']=False
  except PermissionError:result['private_denied']=True
  try:
   with socket.socket(socket.AF_UNIX) as s:s.connect(str(root/'docker.sock'))
   result['docker_denied']=False
  except PermissionError:result['docker_denied']=True
 except Exception as e:result['unavailable']=str(e)
 os.write(write,json.dumps(result).encode());os._exit(0)
os.close(write);proof=json.loads(os.read(read,65536));os.waitpid(pid,0);allowed.close();trap.close()
if 'unavailable' in proof:print(json.dumps({'guard':proof,'target_host_required':True}));sys.exit(2)
assert all(proof[k] for k in ['tcp_loopback','tcp_external','udp','raw','unix_allowed','tcp_listen_allowed','private_denied','docker_denied']),proof
# Execute the actual Linux central binary with the guard and a fictional Unix broker.
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  self.rfile.read(int(self.headers.get('Content-Length','0')))
  if self.path=='/admin/list':value={'projects':[{'slug':'a','models':['test-project-shared'],'state':{'authorized':True}}]}
  elif self.path=='/v1/messages':value={'id':'linux-fixture','type':'message','role':'assistant','model':'test-project-shared','content':[{'type':'text','text':'OK'}],'stop_reason':'end_turn','usage':{'input_tokens':1,'output_tokens':1}}
  else:value={}
  raw=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
class Server(socketserver.ThreadingMixIn,socketserver.UnixStreamServer):daemon_threads=True
server=Server(str(control/'model.sock'),Handler);os.chmod(control/'model.sock',0o660);os.chown(control/'model.sock',21001,21002);threading.Thread(target=server.serve_forever,daemon=True).start()
with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
key='test-linux-key';cfg={'host':'127.0.0.1','port':port,'auth-dir':str(central/'auth-empty'),'api-keys':[key],'remote-management':{'secret-key':key},'routing':{'strategy':'fill-first','retry':{'request-retry':0}}}
(central/'auth-empty').mkdir();os.chown(central/'auth-empty',21003,21003);(central/'config.yaml').write_text(json.dumps(cfg));os.chown(central/'config.yaml',21003,21003)
def before():os.setgroups([21002]);os.setgid(21003);os.setuid(21003)
env={'HOME':str(central),'PATH':'/usr/bin:/bin','TMPDIR':'/tmp','CPA_CONTAINER_ROUTING':'1','CPA_CONTAINER_SOCKET':str(control/'model.sock')}
with (root/'central.log').open('wb') as log:
 process=subprocess.Popen(['python3','-B','/tmp/network_guard.py','--','/tmp/central','-config',str(central/'config.yaml'),'-local-model'],cwd=central,env=env,stdout=log,stderr=log,preexec_fn=before)
 try:
  for _ in range(100):
   try:
    c=http.client.HTTPConnection('127.0.0.1',port,timeout=2);c.request('GET','/healthz');response=c.getresponse();response.read();c.close()
    if response.status==200:break
   except OSError:pass
   time.sleep(.1)
  c=http.client.HTTPConnection('127.0.0.1',port,timeout=10);c.request('POST','/v1/messages',json.dumps({'model':'test-project-shared','messages':[{'role':'user','content':'fictional task'}],'max_tokens':16}),{'Authorization':'Bearer '+key,'Content-Type':'application/json'})
  response=c.getresponse();body=json.loads(response.read());assert response.status==200 and body['content'][0]['text']=='OK',(response.status,body);c.close()
  proof['actual_linux_central_unix_dispatch']=True
 except BaseException:
  print((root/'central.log').read_text(),file=sys.stderr);raise
 finally:
  process.terminate();process.wait(10);server.shutdown();server.server_close()
print(json.dumps({'guard':proof,'systemd_boot_tested':False,'real_accounts_used':False,'host_docker_socket_mounted':False}))

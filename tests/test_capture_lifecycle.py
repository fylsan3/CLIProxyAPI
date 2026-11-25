import contextlib,errno,http.client,http.server,json,select,socket,sys,tempfile,threading,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import request_sample as sample

@contextlib.contextmanager
def fixture(mode):
 started=threading.Event();release=threading.Event();cancelled=threading.Event()
 class Origin(http.server.BaseHTTPRequestHandler):
  protocol_version='HTTP/1.1'
  def log_message(self,*args):pass
  def do_POST(self):
   self.rfile.read(int(self.headers['Content-Length']));started.set()
   if mode=='wait':release.wait(5)
   self.send_response(200);self.send_header('Content-Length','100000' if mode=='cancel' else '2');self.end_headers()
   self.wfile.write(b'x' if mode=='cancel' else b'OK');self.wfile.flush()
   if mode=='cancel':
    ready,_,_=select.select([self.connection],[],[],4)
    if ready and self.connection.recv(1)==b'':cancelled.set()
   self.close_connection=True
 with tempfile.TemporaryDirectory() as tmp:
  root=Path(tmp);root.chmod(0o700)
  origin=http.server.ThreadingHTTPServer(('127.0.0.1',0),Origin)
  proxy=sample.CaptureServer('http://127.0.0.1:'+str(origin.server_port),sample.Recording(root/'samples','m'))
  for srv in (origin,proxy):threading.Thread(target=srv.serve_forever,kwargs={'poll_interval':.05},daemon=True).start()
  try:yield root,proxy,started,release,cancelled
  finally:
   release.set();proxy.shutdown();proxy.server_close();origin.shutdown();origin.server_close()

class LifecycleTest(unittest.TestCase):
 def send(self,proxy):
  c=http.client.HTTPConnection('127.0.0.1',proxy.server_port,timeout=6)
  try:
   c.request('POST','/v1/messages',b'{}',{'X-CPA-Sample':'m'});response=c.getresponse();return response.status,response.read()
  finally:c.close()
 def test_listener_stop_keeps_active_reply(self):
  with fixture('wait') as (root,proxy,started,release,cancelled):
   result=[];t=threading.Thread(target=lambda:result.append(self.send(proxy)));t.start()
   self.assertTrue(started.wait(2));proxy.shutdown();self.assertTrue(t.is_alive());release.set();t.join(3)
   self.assertEqual(result,[(200,b'OK')])
 def test_client_cancellation_reaches_origin(self):
  with fixture('cancel') as (root,proxy,started,release,cancelled):
   c=socket.create_connection(('127.0.0.1',proxy.server_port),timeout=3)
   c.sendall(b'POST /v1/messages HTTP/1.1\r\nHost: localhost\r\nX-CPA-Sample: m\r\nContent-Length: 2\r\n\r\n{}')
   self.assertTrue(started.wait(2));self.assertIn(b'200',c.recv(4096));c.close()
   self.assertTrue(cancelled.wait(3))
   files=[]
   for _ in range(100):
    files=list((root/'samples').glob('sample-*/record.json'))
    if files:break
    time.sleep(.01)
   self.assertTrue(files);self.assertFalse(json.loads(files[0].read_text())['response_complete'])
 def test_sample_disk_error_does_not_replace_reply(self):
  with fixture('normal') as (root,proxy,started,release,cancelled):
   original=sample.os.open
   def failing(path,*args,**kwargs):
    if Path(path).name=='response.bin':raise OSError(errno.ENOSPC,'test disk full')
    return original(path,*args,**kwargs)
   with patch.object(sample.os,'open',failing):self.assertEqual(self.send(proxy),(200,b'OK'))
   self.assertFalse(list((root/'samples').glob('sample-*/record.json')))
if __name__=='__main__':unittest.main(verbosity=2)

import gzip,http.client,http.server,json,os,socket,tempfile,threading,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from request_sample import CaptureServer,Recording,replay,write_private,sha
class Origin(http.server.BaseHTTPRequestHandler):
 protocol_version='HTTP/1.1'
 records=[]
 def log_message(self,*args):pass
 def do_POST(self):
  raw=self.rfile.read(int(self.headers['Content-Length']));Origin.records.append((raw,dict(self.headers)))
  output=b'event: error\r\ndata: {"type":"error","error":{"message":"  raw  "},"extra":1}\r\n\r\n'
  self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(output)));self.end_headers();self.wfile.write(output)
class SampleTest(unittest.TestCase):
 def test_capture_replay_and_guards(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);root.chmod(0o700);origin=http.server.ThreadingHTTPServer(('127.0.0.1',0),Origin)
   threading.Thread(target=origin.serve_forever,daemon=True).start()
   record=Recording(root/'records','single-marker');proxy=CaptureServer('http://127.0.0.1:'+str(origin.server_port),record);threading.Thread(target=proxy.serve_forever,daemon=True).start()
   body=gzip.compress(b'{ "model":"fixture", "messages" : [{"role":"user","content":"private path /example/project"}] }\n')
   def send(marker):
    c=http.client.HTTPConnection('127.0.0.1',proxy.server_port,timeout=10);c.request('POST','/v1/messages?beta=true',[body[:8],body[8:]],{'Content-Type':'application/json','Content-Encoding':'gzip','Authorization':'Bearer credential-canary','X-CPA-Sample':marker},encode_chunked=True)
    response=c.getresponse();data=response.read();c.close();return data
   try:
    before=send('unmarked');self.assertFalse(list((root/'records').glob('sample-*')))
    first=send('single-marker');send('single-marker')
    samples=list((root/'records').glob('sample-*'));self.assertEqual(len(samples),1);sample=samples[0]
    for _ in range(100):
     if (sample/'record.json').exists():break
     threading.Event().wait(.01)
    saved=json.loads((sample/'record.json').read_text());self.assertEqual((sample/'request.bin').read_bytes(),body);self.assertEqual((sample/'response.bin').read_bytes(),first)
    self.assertNotIn('credential-canary',(sample/'record.json').read_text());self.assertTrue(saved['response_complete'])
    state=root/'state';state.mkdir(mode=0o700);(state/'broker-private').mkdir(mode=0o700)
    write_private(state/'client-key',b'a'*48);write_private(state/'launch.json',json.dumps({'ephemeral':True,'api_base':'http://127.0.0.1:'+str(origin.server_port)+'/v1','api_key_file':str(state/'client-key')}).encode());write_private(state/'broker-private/network-fixture.json',b'{"mode":"closed_tls_test"}')
    result=replay(sample,state,root/'replayed');self.assertTrue(result['request_body_unchanged']);self.assertTrue(result['historical_response_match']);self.assertEqual(Origin.records[-1][0],body);self.assertEqual(Origin.records[-1][1]['Authorization'],'Bearer '+'a'*48)
    for p in sample.iterdir():self.assertEqual(p.stat().st_mode&0o777,0o600)
    (state/'broker-private/network-fixture.json').write_bytes(b'{"mode":"managed"}')
    with self.assertRaisesRegex(ValueError,'ephemeral_closed'):replay(sample,state,root/'rejected')
    (state/'broker-private/network-fixture.json').write_bytes(b'{"mode":"closed_tls_test"}');(sample/'request.bin').write_bytes(body+b'x')
    with self.assertRaisesRegex(ValueError,'incomplete_or_changed'):replay(sample,state,root/'tampered')
    expired=Recording(root/'expired','m',-1);self.assertIsNone(expired.claim('m'))
   finally:proxy.shutdown();proxy.server_close();origin.shutdown();origin.server_close()
if __name__=='__main__':unittest.main(verbosity=2)

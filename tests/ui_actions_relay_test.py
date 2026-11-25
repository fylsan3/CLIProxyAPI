import hashlib,http.client,json,socket,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from relay import Relay
from network_control import Control
from proxy_config import parse_proxy

class ProxyViewTests(unittest.TestCase):
 def setup_control(self):
  cfg={'proxy_ip':'2001:db8::1','proxy_port':1080,'username':'fixture:user','password':'fixture@pass'}
  raw=json.dumps(cfg,sort_keys=True)
  card={'network_config':'fixture-network','network_config_sha256':hashlib.sha256(raw.encode()).hexdigest(),'image':'fixture-image'}
  c=Control.__new__(Control);c.load=lambda owner:card
  return c,raw,card,cfg
 def test_view_uses_bound_read_only_network_disk_without_network(self):
  c,raw,card,cfg=self.setup_control()
  with patch('network_control.docker',return_value=raw) as run:
   value=c.proxy_url('A');args=run.call_args.args
  self.assertEqual(parse_proxy(value),cfg)
  self.assertIn('none',args);self.assertIn('type=volume,source=fixture-network,target=/network-config,readonly',args)
  self.assertNotIn('start',args)
 def test_modified_network_configuration_is_not_displayed(self):
  c,raw,card,cfg=self.setup_control()
  with patch('network_control.docker',return_value=raw+' '):
   with self.assertRaisesRegex(ValueError,'network_config_changed'):c.proxy_url('A')

class RelayTests(unittest.TestCase):
 def create_relay(self,response):
  r=Relay([], 'fictional-container','fixture-session',lambda:None,lambda:None)
  # Feed a real pipe in fragments, exercising the same forwarding loop without Docker.
  script="import os,sys;data=b''\nwhile b'\\r\\n\\r\\n' not in data:data+=os.read(0,4096)\nraw="+repr(response)+"\nfor at in range(0,len(raw),71):os.write(1,raw[at:at+71])"
  r.cmd=[sys.executable,'-u','-c',script];self.addCleanup(r.close);return r
 def test_static_response_declares_close_and_preserves_all_bytes(self):
  payload=b'large-test-component-'*4096
  response=b'HTTP/1.1 200 OK\r\nContent-Type: text/javascript\r\nConnection: keep-alive\r\nKeep-Alive: timeout=5\r\nContent-Length: '+str(len(payload)).encode()+b'\r\n\r\n'+payload
  r=self.create_relay(response);c=http.client.HTTPConnection(*r.server_address,timeout=5)
  try:
   c.request('GET','/'+r.token+'/core/rfb.js');res=c.getresponse()
   self.assertEqual(res.status,200);self.assertEqual(res.getheader('Connection'),'close');self.assertIsNone(res.getheader('Keep-Alive'));self.assertEqual(res.read(),payload)
  finally:c.close()
 def test_websocket_upgrade_and_frame_are_unchanged(self):
  raw=b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n\r\n\x82\x03RFB'
  r=self.create_relay(raw)
  with socket.create_connection(r.server_address,timeout=5) as s:
   s.sendall(('GET /'+r.token+'/websockify HTTP/1.1\r\nHost: '+r.authority+'\r\nOrigin: http://'+r.authority+'\r\nUpgrade: websocket\r\n\r\n').encode())
   data=b''
   while True:
    b=s.recv(4096)
    if not b:break
    data+=b
   self.assertEqual(data,raw)
 def test_wrong_token_cannot_load_viewer(self):
  r=self.create_relay(b'');c=http.client.HTTPConnection(*r.server_address,timeout=5)
  try:c.request('GET','/wrong/desktop.html');self.assertEqual(c.getresponse().status,404)
  finally:c.close()
 def test_cross_origin_websocket_is_rejected(self):
  r=self.create_relay(b'')
  with socket.create_connection(r.server_address,timeout=5) as s:
   s.sendall(('GET /'+r.token+'/websockify HTTP/1.1\r\nHost: '+r.authority+'\r\nOrigin: http://untrusted.invalid\r\nUpgrade: websocket\r\n\r\n').encode())
   self.assertEqual(s.recv(4096),b'')

if __name__=='__main__':unittest.main()

"""Pure contract/security tests; no production, account or network access."""
import importlib.util,json,os,sys,tempfile,unittest,socket,socketserver,threading,http.server
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'image'))
import claude_code as cli
import claude_code_control as bridge

class Tests(unittest.TestCase):
 def test_caller_cannot_supply_command_or_environment(self):
  for values in ({'command':'sh'},{'env':{}},{'cwd':'/state'}):
   self.assertEqual(bridge.command(None,'a','job-start',values)[0],400)
 def test_invalid_account_is_rejected_before_docker(self):
  for name in ('../a','a/b','A',''):
   self.assertEqual(bridge.command(None,name,'status',{})[0],400)
 def test_browser_only_accepts_official_auth_path(self):
  for url in ('http://claude.ai/oauth/authorize','https://claude.ai.evil/oauth/authorize','https://user@claude.ai/oauth/authorize','https://claude.ai/new','https://claude.ai:444/oauth/authorize'):
   with self.assertRaises(ValueError):cli.browser_open(url)
  with patch.object(cli,'rpc',return_value={'ok':True}) as rpc:
   self.assertTrue(cli.browser_open('https://claude.ai/oauth/authorize?state=fixture')['ok']);self.assertEqual(rpc.call_args.args[1]['op'],'open-claude-browser')
   self.assertTrue(cli.browser_open('https://claude.com/cai/oauth/authorize?state=fixture')['ok'])
 def test_environment_uses_persistent_account_home_and_proxy(self):
  with tempfile.TemporaryDirectory() as tmp,patch.object(cli,'ROOT',Path(tmp)),patch.dict(os.environ,{'ANTHROPIC_API_KEY':'must-not-inherit','CLAUDE_CODE_OAUTH_TOKEN':'must-not-inherit','CPA_PROVIDER':'claude-subscription'},clear=True):
   env=cli.environment();self.assertNotIn('ANTHROPIC_API_KEY',env);self.assertNotIn('CLAUDE_CODE_OAUTH_TOKEN',env)
   self.assertEqual(env['HTTPS_PROXY'],'http://127.0.0.1:18080');self.assertEqual(env['DISABLE_AUTOUPDATER'],'1');self.assertTrue(Path(env['HOME']).exists())
 def test_timeout_at_least_one_hour(self):self.assertGreaterEqual(cli.MAX_SECONDS,3600)
 def test_unknown_operation_is_rejected(self):
  service=cli.Service.__new__(cli.Service)
  with self.assertRaises(ValueError):service.dispatch({'op':'shell'})
 def test_connect_sends_domain_to_account_socks_and_preserves_bytes(self):
  observed=[]
  class Socks(socketserver.BaseRequestHandler):
   def handle(self):
    s=self.request;self.server.observed.append(cli.exact(s,3));s.sendall(b'\x05\x00')
    head=cli.exact(s,4);host=cli.exact(s,cli.exact(s,1)[0]);port=cli.exact(s,2)
    self.server.observed.append((head,host,port));s.sendall(b'\x05\x00\x00\x01\x7f\x00\x00\x01\x01\xbb')
    while True:
     data=s.recv(65536)
     if not data:break
     s.sendall(data)
  socks=socketserver.ThreadingTCPServer(('127.0.0.1',0),Socks);socks.observed=observed;socks.daemon_threads=True
  proxy=http.server.ThreadingHTTPServer(('127.0.0.1',0),cli.Connect)
  for s in (socks,proxy):threading.Thread(target=s.serve_forever,daemon=True).start()
  real_connect=socket.create_connection
  def account_connect(address,**kwargs):
   self.assertEqual(address,('127.0.0.1',1080));return real_connect(socks.server_address,**kwargs)
  try:
   with patch.object(cli,'check_network'),patch.object(cli.socket,'create_connection',side_effect=account_connect):
    with real_connect(proxy.server_address,timeout=3) as client:
     client.sendall(b'CONNECT example.invalid:443 HTTP/1.1\r\nHost: example.invalid:443\r\n\r\n');headers=b''
     while not headers.endswith(b'\r\n\r\n'):headers+=client.recv(1)
     self.assertIn(b'200 Connection Established',headers)
     payload=b'\x16\x03\x01opaque-TLS-test\x00\xff';client.sendall(payload);self.assertEqual(cli.exact(client,len(payload)),payload)
   self.assertEqual(observed,[b'\x05\x01\x00',(b'\x05\x01\x00\x03',b'example.invalid',b'\x01\xbb')])
   with patch.object(cli,'check_network',side_effect=ValueError('account_proxy_unavailable')),patch.object(cli.socket,'create_connection') as dial:
    with real_connect(proxy.server_address,timeout=3) as client:
     client.sendall(b'CONNECT example.invalid:443 HTTP/1.1\r\n\r\n');self.assertIn(b'502',client.recv(4096))
    dial.assert_not_called()
  finally:
   for s in (proxy,socks):s.shutdown();s.server_close()
if __name__=='__main__':unittest.main()

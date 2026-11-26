"""No real inputs: validate redaction and structure with secret canaries."""
import sys,json,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'image'))
from sample_export import Sanitizer
class ExportTest(unittest.TestCase):
 def test_secrets_and_text(self):
  s=Sanitizer();raw={'system':'secret-system','messages':[{'role':'user','content':'secret-content'}],'access_token':'secret-token','metadata':{'private-project':'secret-project'},'id':123456789,'tools':[{'name':'secret-tool','input_schema':{'properties':{'private-file':{'type':'string'}}}}]}
  output=json.dumps(s.tree(raw));self.assertIn('"user"',output)
  for value in ['secret-system','secret-content','secret-token','private-project','secret-project','123456789','secret-tool','private-file']:self.assertNotIn(value,output)
  self.assertEqual(s.token('same'),s.token('same'))
 def test_headers_and_sse(self):
  s=Sanitizer();h=s.headers([('Authorization',['Bearer secret']),('Cookie',['secret-cookie']),('User-Agent',['claude-cli/2.1.331 (external, sdk-cli)']),('X-Other',['secret-extra'])]);v=json.dumps(h)
  self.assertIn('claude-cli/2.1.331',v)
  for secret in ['Bearer secret','secret-cookie','secret-extra']:self.assertNotIn(secret,v)
  sse=b'event: content_block_delta\ndata: {"type":"text_delta","text":"secret-reply"}\n\n'
  value=json.dumps(s.body(sse,{}));self.assertNotIn('secret-reply',value);self.assertIn('text_delta',value)
if __name__=='__main__':unittest.main()

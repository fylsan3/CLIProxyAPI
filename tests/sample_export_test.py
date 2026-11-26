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
 def test_header_values_are_bound_to_names(self):
  s=Sanitizer();h=s.headers([('Authorization',['application/json']),('Cookie',['keep-alive']),('X-Client-Request-Id',['node']),('X-Other',['Linux']),('User-Agent',['application/json']),('Content-Type',['application/json'])])
  for row in h[:-1]:self.assertTrue(row['values'][0].startswith('redacted_'))
  self.assertEqual(h[-1]['values'],['application/json'])
 def test_shared_generated_policy(self):
  from sample_export import POLICY,HEADER_VALUES
  self.assertEqual(POLICY['policy_version'],'account-egress-4-single-source')
  self.assertEqual(len(POLICY['policy_sha256']),64)
  self.assertIn('axios/1.15.2',HEADER_VALUES['user-agent'])
  self.assertIn('claude-code/2.1.331',HEADER_VALUES['user-agent'])
  self.assertNotIn('authorization',HEADER_VALUES)
 def test_before_after_comparison_is_sanitized(self):
  s=Sanitizer();q={'before_override':{'headers':{'Authorization':['Bearer SECRET'],'User-Agent':['PRIOR_SECRET_AGENT'],'X-Secret':['SECRET']},'close':True},'headers':{'Authorization':['Bearer SECRET'],'User-Agent':['claude-code/2.1.331'],'X-Secret':['SECRET']},'close':False,'wire_headers':[{'name':'Authorization','values':['Bearer SECRET']},{'name':'User-Agent','values':['claude-code/2.1.331']},{'name':'X-Secret','values':['SECRET']},{'name':'Host','values':['api.anthropic.com']}]}
  v=s.header_comparison(q);raw=json.dumps(v)
  self.assertTrue(v['available']);self.assertNotIn('SECRET',raw)
  self.assertEqual([x['name'] for x in v['policy_changes']],['user-agent'])
  self.assertEqual([x['name'] for x in v['transport_changes']],['host'])
  self.assertTrue(v['close_before']);self.assertFalse(v['close_after'])
  self.assertFalse(s.header_comparison({})['available'])
 def test_incomplete_response_does_not_hide_request_headers(self):
  from unittest.mock import patch
  import tempfile,json,hashlib,struct,os
  from pathlib import Path
  from cryptography.hazmat.primitives.ciphers.aead import AESGCM
  import http_archive
  with tempfile.TemporaryDirectory() as tmp:
   folder=Path(tmp)/'archive'/'0001';folder.mkdir(parents=True)
   key=os.urandom(32)
   def seal(name,raw):
    chunks=[]
    for data in (raw,b''):
     nonce=os.urandom(12);value=nonce+AESGCM(key).encrypt(nonce,data,name.encode());chunks.append(struct.pack('>I',len(value))+value)
    path=folder/name;path.write_bytes(b'CPAENC1\n'+b''.join(chunks));path.chmod(0o600)
   body=b'{}';reply=b'partial-response-secret'
   common={'archive_id':'archive','exchange':'0001'}
   q=dict(common,method='GET',url='https://api.anthropic.com/api/oauth/profile',headers={'User-Agent':['claude-code/2.1.331']},wire_headers=[{'name':'User-Agent','values':['claude-code/2.1.331']}],complete=True,bytes=len(body),sha256=hashlib.sha256(body).hexdigest(),write_succeeded=True,write_attempts=1)
   r=dict(common,status=200,headers={},complete=False,bytes=len(reply),sha256=hashlib.sha256(reply).hexdigest())
   for name,raw in [('request.json.enc',json.dumps(q).encode()),('response.json.enc',json.dumps(r).encode()),('request.bin.enc',body),('response.bin.enc',reply)]:seal(name,raw)
   with self.assertRaises(ValueError):http_archive.load_exchange(folder,key)
   sample=Sanitizer().exchange(folder,key)
   self.assertTrue(sample['completeness']['request']);self.assertFalse(sample['completeness']['response']);self.assertFalse(sample['completeness']['original_full_replay_eligible'])
   self.assertEqual(sample['request']['headers'][0]['values'],['claude-code/2.1.331']);self.assertNotIn('partial-response-secret',json.dumps(sample))
   p=folder/'response.bin.enc';p.write_bytes(p.read_bytes()[:-1])
   with self.assertRaises(Exception):Sanitizer().exchange(folder,key)
if __name__=='__main__':unittest.main()

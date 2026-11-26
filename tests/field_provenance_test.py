import json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'image'))
from field_provenance import compare
from sample_export import Sanitizer

class FieldProvenanceTests(unittest.TestCase):
 def test_add_remove_identity_and_unknown_field_privacy(self):
  a={'system':'PRIVATE_SYSTEM','messages':[{'role':'user','content':'darwin'}], 'metadata':{'user_id':json.dumps({'device_id':'PRIVATE_OLD','session_id':'PRIVATE_SESSION'}),'PRIVATE_KEY':'PRIVATE_VALUE'}}
  b={'system':'PRIVATE_SYSTEM','messages':[{'role':'user','content':'darwin'}], 'metadata':{'user_id':json.dumps({'device_id':'PRIVATE_NEW','session_id':'PRIVATE_SESSION','account_uuid':'PRIVATE_ACCOUNT'})}}
  v=compare(a,b,Sanitizer(b'A'*32));text=json.dumps(v)
  self.assertNotIn('PRIVATE',text);self.assertFalse(v['truncated'])
  paths={r['path'] for r in v['changes']};self.assertIn('/metadata/user_id/$json/device_id',paths);self.assertIn('/metadata/user_id/$json/account_uuid',paths)
  self.assertFalse(any(p.startswith('/messages') or p.startswith('/system') for p in paths))
 def test_metadata_type_changes_and_limit_are_not_silent(self):
  self.assertFalse(compare({'metadata':{}},{'metadata':None},Sanitizer())['equal'])
  v=compare(list(range(20)),list(range(1,21)),Sanitizer(),limit=2)
  self.assertTrue(v['truncated']);self.assertFalse(v['equal'])
 def test_request_scopes_are_not_shared(self):
  a=Sanitizer(b'A'*32);b=Sanitizer(b'B'*32)
  self.assertNotEqual(compare({}, {'system':'same'},a)['changes'][0]['after'],compare({}, {'system':'same'},b)['changes'][0]['after'])
if __name__=='__main__':unittest.main()

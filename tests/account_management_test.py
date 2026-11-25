import sys,unittest,tempfile,threading,time,types
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from account_metadata import Metadata
from portable_backup import Packages
class AccountManagement(unittest.TestCase):
 def test_identity_is_immutable_and_unique_without_tokens(self):
  with tempfile.TemporaryDirectory() as d:
   m=Metadata(d);identity={'key':'a'*64,'email':'a@example.invalid'}
   self.assertEqual(m.bind('a',identity),identity)
   self.assertEqual(m.bind('a',identity),identity)
   with self.assertRaisesRegex(ValueError,'already_bound'):m.bind('b',identity)
   with self.assertRaisesRegex(ValueError,'rebind_denied'):m.bind('a',dict(identity,key='b'*64))
   self.assertEqual(m.identity('a'),identity)
 def test_route_persistence_validation_and_conflict(self):
  with tempfile.TemporaryDirectory() as d:
   m=Metadata(d);self.assertEqual(m.route('a')['weight'],1)
   value=m.patch_route('a',{'priority':10,'weight':25},0)
   self.assertEqual(value['revision'],1)
   self.assertEqual(Metadata(d).route('a'),value)
   with self.assertRaisesRegex(ValueError,'conflict'):m.patch_route('a',{'priority':0},0)
   for fields in ({'weight':True},{'weight':1000001},{'priority':1.5},{'token':'secret'}):
    with self.assertRaises(ValueError):m.patch_route('a',fields)
 def test_auto_backup_is_queued_without_stopping_dispatch(self):
  p=object.__new__(Packages);p.lock=threading.Lock();p.observed_revisions={};p.last_automatic={};p.pending=set()
  p.broker=types.SimpleNamespace(protection=types.SimpleNamespace(state=lambda owner:{'backup_verified':True}))
  notes=[];jobs=[];p.note_revision=lambda owner,rev:notes.append((owner,rev));p.status=lambda owner:{'revision':1};p.enqueue=lambda owner:jobs.append(owner)
  p.observe_revision('A',2);p.observe_revision('A',2)
  self.assertEqual(jobs,['A']);self.assertEqual(notes,[('A',2)])
  p.pending.add('B');p.observe_revision('B',3);self.assertEqual(jobs,['A'])
  p.status=lambda owner:{'revision':4};p.observe_revision('A',4);self.assertEqual(jobs,['A'])
 def test_same_token_revision_does_not_hide_outdated_environment_backup(self):
  import json
  from retention import write_json
  with tempfile.TemporaryDirectory() as d:
   folder=Path(d);card=folder/'A.json';target=folder/'package';target.mkdir()
   current={'owner':'A','environment_id':'fixture-id','image':'new-image'};write_json(card,current)
   receipt={'revision':2,'exported_at':1,'spec':{'card':dict(current,image='old-image')}};write_json(target/'latest.json',receipt)
   p=object.__new__(Packages);p.folder=folder;p.destination=target;p.metadata_warnings=set();p.target=lambda card:target
   p.broker=types.SimpleNamespace(protection=types.SimpleNamespace(control=types.SimpleNamespace(card=lambda owner:card)))
   state=p.status('A');self.assertTrue(state['environment_outdated']);self.assertTrue(state['warning']);self.assertFalse(state['stale'])
   receipt['spec']['card']=current;write_json(target/'latest.json',receipt)
   self.assertFalse(p.status('A')['warning'])
if __name__=='__main__':unittest.main(verbosity=2)

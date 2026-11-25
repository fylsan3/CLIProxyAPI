import concurrent.futures,threading,unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from maintenance import MaintenanceGate
from central_view import merge_central
from worker_sample import input_hash
import hashlib,json

class Gates(unittest.TestCase):
 def test_busy_restart_refused_and_B_unaffected(self):
  gate=MaintenanceGate()
  with gate.request('A'):
   with self.assertRaisesRegex(ValueError,'account_busy'):
    with gate.maintenance('A'):pass
   with gate.maintenance('B'):self.assertTrue(gate.status('B')['maintenance'])
  with gate.maintenance('A'):
   with self.assertRaisesRegex(ValueError,'account_maintenance'):
    with gate.request('A'):pass
   with gate.request('B'):pass
  with gate.request('A'):pass
 def test_race_never_admits_during_maintenance(self):
  gate=MaintenanceGate();barrier=threading.Barrier(2);events=[];lock=threading.Lock()
  def request():
   barrier.wait()
   try:
    with gate.request('A'):
     with lock:events.append('request')
   except ValueError:pass
  def restart():
   barrier.wait()
   try:
    with gate.maintenance('A'):
     self.assertEqual(gate.status('A')['admitted_requests'],0)
     with lock:events.append('restart')
   except ValueError:pass
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lambda f:f(),[request,restart]))
  self.assertTrue(events)
 def test_refresh_and_browser_operations_share_restart_gate(self):
  from broker import Broker
  import types
  broker=object.__new__(Broker);broker.gate=MaintenanceGate();broker.registry=types.SimpleNamespace(get=lambda slug:{'owner':slug.upper()})
  seen=[]
  def execute(action,body,connection=None):
   with self.assertRaisesRegex(ValueError,'account_busy'):
    with broker.gate.maintenance('A'):pass
   with broker.gate.request('A'):seen.append('model_still_admitted')
   return 200,{}
  broker.admin_execute=execute
  for action in ['refresh-check','refresh-execute','auth-begin','open-browser']:
   self.assertEqual(broker.admin(action,{'slug':'a'})[0],200)
   with broker.gate.maintenance('A'):self.assertEqual(broker.admin(action,{'slug':'a'})[0],409)
  self.assertEqual(len(seen),4)
 def test_snapshot_readiness_not_just_authorized(self):
  result={'projects':[{'slug':'a','ready':True},{'slug':'b','ready':False}]}
  merge_central(result,{'started':True,'accounts':[{'slug':'a','dispatch':{'eligible':False}},{'slug':'b','dispatch':{'eligible':True}}],'scheduler_config':{'strategy':'fill-first'},'in_flight':2})
  self.assertFalse(any(p['overall_ready'] for p in result['projects']));self.assertEqual(result['scheduler_in_flight'],2)
 def test_sample_input_hash_matches_broker_encoding(self):
  raw=b'{"messages":[{"content":"timezone Asia/Tokyo"}], "model":"fixture"}'
  self.assertEqual(input_hash(raw),hashlib.sha256(json.dumps(json.loads(raw)).encode()).hexdigest())
 def test_unavailable_scheduler_never_reuses_stale_config_or_zero_count(self):
  result={'projects':[{'slug':'a','ready':True,'state':{'active_calls':2}}]}
  merge_central(result,{'started':False,'accounts':[{'slug':'a','dispatch':{'eligible':True}}],'scheduler_config':{'strategy':'fill-first'},'in_flight':0})
  self.assertFalse(result['projects'][0]['overall_ready'])
  self.assertIsNone(result['scheduler_config']);self.assertIsNone(result['scheduler_in_flight'])
  self.assertEqual(result['projects'][0]['state']['active_calls'],2)
if __name__=='__main__':unittest.main(verbosity=2)

import json,sqlite3,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from account_metrics import initialize,summarize,tokens
from resource_monitor import aggregate,cpu_percent,reduce_points,PROBE

class Metrics(unittest.TestCase):
 def setUp(self):
  self.db=sqlite3.connect(':memory:');self.db.execute('CREATE TABLE attempts(owner TEXT,started INTEGER,state TEXT,status INTEGER,usage TEXT)');initialize(self.db);self.now=1000000
  self.db.execute("UPDATE metric_meta SET value=?",(self.now-120,))
 def tearDown(self):self.db.close()
 def add(self,started,state='completed',status=200,owner='A',finished=None,usage=None):
  self.db.execute('INSERT INTO attempts VALUES(?,?,?,?,?,?)',(owner,started,state,status,json.dumps(usage or {'state':'confirmed','values':{'input_tokens':10,'output_tokens':3}}),finished))
 def test_windows_and_accounts(self):
  for t in [self.now-61,self.now-60,self.now-59,self.now]:self.add(t,finished=self.now)
  self.add(self.now-7*86400);self.add(self.now,owner='B');self.add(self.now-2,'result_unknown',200);self.add(self.now-1,'completed',403)
  r=summarize(self.db,'A',self.now);self.assertEqual(r['rpm'],4);self.assertEqual(r['peak_rpm'],4);self.assertEqual(r['seven_day']['success'],4);self.assertEqual(r['seven_day']['failed'],1);self.assertEqual(r['seven_day']['unknown'],1);self.assertEqual(r['tpm'],52)
 def test_long_task_completion_and_legacy(self):
  self.add(self.now-4000,finished=self.now-1);self.add(self.now-1) # historical completion time missing
  r=summarize(self.db,'A',self.now);self.assertEqual(r['tpm'],13);self.assertEqual(r['rpm'],1)
  self.db.execute('UPDATE metric_meta SET value=?',(self.now-10,));self.assertIsNone(summarize(self.db,'A',self.now)['tpm'])
 def test_empty_and_invalid(self):
  r=summarize(self.db,'A',self.now);self.assertEqual(r['rpm'],0);self.assertIsNone(r['last_request_at']);self.assertEqual(r['tpm'],0)
  for raw in [None,'bad','[]',json.dumps({'state':'confirmed','values':{'input_tokens':True,'output_tokens':2}})]:self.assertIsNone(tokens(raw))
 def test_resource_missing_and_reset(self):
  self.assertEqual(cpu_percent({'at':0,'container':'a','cpu_usec':0},{'at':30,'container':'a','cpu_usec':15000000}),50)
  self.assertIsNone(cpu_percent({'at':0,'container':'a','cpu_usec':90},{'at':30,'container':'a','cpu_usec':1}))
  self.assertIsNone(cpu_percent({'at':0,'container':'a','cpu_usec':0},{'at':30,'container':'b','cpu_usec':1}))
  self.assertIsNone(aggregate([{'memory_bytes':100},{'error':'unavailable'}],30)['memory_bytes'])
  rows=[{'at':1,'memory_bytes':10,'cpu_percent':5,'disk_bytes':100},{'at':2,'memory_bytes':30,'cpu_percent':15,'disk_bytes':100}]
  p=reduce_points(rows,300)[0];self.assertEqual(p['memory_bytes'],20);self.assertEqual(p['memory_bytes_peak'],30)
  rows[0]['memory_bytes']=None;self.assertIsNone(reduce_points(rows,300)[0]['memory_bytes'])
  compile(PROBE,'probe','exec')

if __name__=='__main__':unittest.main(verbosity=2)

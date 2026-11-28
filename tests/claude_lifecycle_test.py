"""Injected subprocess faults; Linux process cleanup, no accounts or external I/O."""
import os,sys,tempfile,time,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,'/opt/native')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'image'))
import claude_code as cli

@unittest.skipUnless(sys.platform=='linux','Process ownership is implemented in the Ubuntu container; run through integration fixture')
class Lifecycle(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'workspace').mkdir()
  self.binary=self.root/'fake-cli';self.binary.write_text('#!/usr/bin/python3\n');self.binary.chmod(0o700)
  self.patches=[patch.object(cli,'ROOT',self.root),patch.object(cli,'BINARY',str(self.binary)),patch.object(cli,'check_network'),patch.object(cli,'shared_snapshot',return_value=SimpleNamespace(access_token='fictional-only',revision=1)),patch.object(cli,'shared_status',return_value={'ready':True,'refresh_owner':'go'}),patch.object(cli,'environment',return_value={'PATH':'/usr/bin:/bin'})]
  for p in self.patches:p.start()
  self.service=cli.Service()
 def tearDown(self):
  self.service.close()
  for p in reversed(self.patches):p.stop()
  self.tmp.cleanup()
 def code(self,body):self.binary.write_text('#!/usr/bin/python3\n'+body)
 def wait(self,fn,seconds=8):
  end=time.monotonic()+seconds
  while time.monotonic()<end:
   v=fn()
   if v:return v
   time.sleep(.03)
  self.fail('condition timed out')
 def start(self):return self.service.dispatch({'op':'job-start','prompt':'hello'})['id']
 def finished(self,j):return self.wait(lambda:self.service.jobs[j]['state'] not in cli.ACTIVE_STATES)
 def test_idle_and_status_do_not_start_cli(self):
  self.service.close()
  with patch.object(cli.subprocess,'Popen') as popen,patch.object(cli.subprocess,'check_output') as run:
   self.service=cli.Service()
   for _ in range(3):self.assertEqual(self.service.dispatch({'op':'status'})['state'],'idle')
   popen.assert_not_called();run.assert_not_called()
 def test_completion_cleanup_before_new_job(self):
  self.code('import json,sys\nsys.stdin.read()\nprint(json.dumps({"type":"result","result":"OK"}))\n')
  for _ in range(2):
   j=self.start();self.finished(j);self.assertEqual(self.service.jobs[j]['state'],'succeeded');self.assertFalse(cli.group_alive(self.service.jobs[j]['process'].pid))
 def test_crash_cleans_stubborn_orphan_and_preserves_status(self):
  marker=self.root/'child'
  self.code('import os,time,signal\np=os.fork()\nif p==0:\n signal.signal(signal.SIGTERM,signal.SIG_IGN)\n open('+repr(str(marker))+',"w").write(str(os.getpid()))\n time.sleep(90)\nelse:\n time.sleep(.1)\n os._exit(17)\n')
  j=self.start();self.wait(marker.exists);self.wait(lambda:self.service.jobs[j]['state']=='cleaning')
  start=time.monotonic();self.assertEqual(self.service.dispatch({'op':'status'})['state'],'cleaning');self.assertLess(time.monotonic()-start,.5)
  with self.assertRaises(ValueError):self.start()
  self.finished(j);self.assertEqual(self.service.jobs[j]['state'],'failed');self.assertFalse(Path('/proc/'+marker.read_text()).exists())
 def test_cancel_nonreading_stubborn_process(self):
  self.code('import signal,time\nsignal.signal(signal.SIGTERM,signal.SIG_IGN)\ntime.sleep(90)\n')
  j=self.service.start_job({'prompt':'x'*65536})['id'];self.wait(lambda:self.service.jobs[j]['process'] is not None);time.sleep(.1)
  self.service.dispatch({'op':'job-cancel','id':j});self.finished(j);self.assertEqual(self.service.jobs[j]['state'],'cancelled');self.assertFalse(cli.group_alive(self.service.jobs[j]['process'].pid))
 def test_cancel_during_start_does_not_spawn(self):
  entered=threading.Event();release=threading.Event();original=cli.shared_snapshot
  def delayed(*args):
   if threading.current_thread()!=threading.main_thread():entered.set();release.wait(4)
   return original(*args)
  with patch.object(cli,'shared_snapshot',side_effect=delayed),patch.object(cli.subprocess,'Popen') as popen:
   j=self.start();self.assertTrue(entered.wait(2));self.service.dispatch({'op':'job-cancel','id':j});release.set();self.finished(j);popen.assert_not_called()
  self.assertEqual(self.service.jobs[j]['state'],'cancelled')
 def test_launch_exception_and_bad_terminal_size_release_resources(self):
  self.binary.unlink();j=self.start();self.finished(j);self.assertEqual(self.service.jobs[j]['state'],'failed')
  with self.assertRaises(ValueError):self.service.start_terminal({'cols':1})
  self.assertFalse(self.service.terminal_running())
 def test_terminal_close_cleanup_and_shutdown(self):
  self.code('import time\ntime.sleep(90)\n')
  t=self.service.start_terminal({});self.assertTrue(self.service.terminal_running());self.service.dispatch({'op':'terminal-stop','id':t['id']});self.assertFalse(self.service.terminal_running());self.assertFalse(cli.group_alive(self.service.terminal['process'].pid))
  j=self.start();self.wait(lambda:self.service.jobs[j]['process'] is not None);self.service.close();self.assertEqual(self.service.jobs[j]['state'],'cancelled')
  with self.assertRaises(ValueError):self.start()
 def test_cleanup_failure_stays_busy(self):
  self.code('import sys\nsys.exit(1)\n')
  with patch.object(cli,'terminate',side_effect=RuntimeError('fixture failure')):
   j=self.start();self.wait(self.service.jobs[j]['done'].is_set);self.assertTrue(self.service.busy());self.assertEqual(self.service.jobs[j]['error'],'claude_cleanup_incomplete')
  cli.terminate(self.service.jobs[j]['process'])
if __name__=='__main__':unittest.main(verbosity=2)

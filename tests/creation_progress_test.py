import json,sys,tempfile,threading,time,unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from creation_progress import CreationFailure,STEPS,safe_error
from creation_probe import discover
from protection import Protection

class CreationTests(unittest.TestCase):
    def test_invalid_proxy_has_actionable_validation_error(self):
        from dashboard import action
        code,body=action(None,{'action':'create','slug':'a','proxy_url':'invalid-proxy'})
        self.assertEqual(code,400);self.assertEqual(body['error'],'invalid_proxy_config')
    def setup_protection(self,create):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        p=Protection.__new__(Protection);p.control=SimpleNamespace(folder=Path(temp.name),registry=SimpleNamespace(get=lambda _:{}),create=create)
        p.locks={};p.locks_guard=threading.Lock();return p
    def test_success_records_every_real_callback(self):
        def create(owner,proxy,progress):
            for step in STEPS:progress(step)
            return {'environment_id':'fake-environment'}
        p=self.setup_protection(create);p.create('A','not-a-real-proxy')
        state=json.loads(p.record('A').read_text())
        self.assertEqual([s['step'] for s in state['creation_steps']],list(STEPS))
        self.assertTrue(all(s['status']=='completed' for s in state['creation_steps']))
        self.assertEqual(state['phase'],'awaiting_authorization')
        self.assertFalse(state['backup_verified'])
    def test_status_is_readable_while_creation_is_in_progress(self):
        from broker import Broker
        entered=threading.Event();release=threading.Event();errors=[]
        def create(owner,proxy,progress):
            progress('checking_socks');entered.set()
            if not release.wait(3):raise RuntimeError('test_wait_expired')
            return {'environment_id':'fake-environment'}
        p=self.setup_protection(create)
        from maintenance import MaintenanceGate
        b=Broker.__new__(Broker);b.protection=p;b.offline_only=True;b.inspect=lambda _:None;b.gate=MaintenanceGate()
        def run():
            try:p.create('A','fake')
            except Exception as e:errors.append(e)
        worker=threading.Thread(target=run);worker.start()
        try:
            self.assertTrue(entered.wait(1));started=time.monotonic()
            state=b.status('A')
            self.assertLess(time.monotonic()-started,.5)
            self.assertEqual(state['protection']['creation_steps'][0]['status'],'running')
        finally:release.set();worker.join(4)
        self.assertFalse(worker.is_alive());self.assertFalse(errors)
    def test_failure_retains_failed_step_and_no_secret(self):
        def create(owner,proxy,progress):
            progress('checking_socks');progress('checking_exit');raise ValueError('secret-user:secret-password@host')
        p=self.setup_protection(create)
        with self.assertRaises(CreationFailure):p.create('A','fake')
        raw=p.record('A').read_text();self.assertNotIn('secret-password',raw)
        state=json.loads(raw);self.assertEqual(state['creation_error'],'exit_timezone_unavailable')
        self.assertEqual([s['status'] for s in state['creation_steps']],['completed','failed'])
    def test_interrupted_creation_becomes_failure_on_recovery(self):
        p=self.setup_protection(None);p.phase('A','creating',creation_steps=[{'step':'preparing_storage','status':'running'}])
        p.recover_creation('A');self.assertEqual(p.state('A')['creation_error'],'creation_interrupted')
        self.assertEqual(p.state('A')['creation_steps'][0]['status'],'failed')
    def test_known_auth_error_reaches_caller(self):
        script="import sys,json;json.load(sys.stdin);print(json.dumps({'error':'proxy_auth_rejected'}),flush=True);sys.exit(1)"
        with self.assertRaisesRegex(CreationFailure,'proxy_auth_rejected'):discover([sys.executable,'-c',script],{},lambda _:None)
    def test_untrusted_probe_error_is_sanitized(self):
        script="import sys,json;json.load(sys.stdin);print(json.dumps({'error':'PASSWORD-secret'}),flush=True);sys.exit(1)"
        with self.assertRaisesRegex(CreationFailure,'^creation_failed$'):discover([sys.executable,'-c',script],{},lambda _:None)
    def test_streamed_step_and_valid_result(self):
        script="import sys,json;json.load(sys.stdin);print(json.dumps({'step':'checking_exit'}),flush=True);print(json.dumps({'location':{'timezone':'Etc/UTC','exit_ip':'192.0.2.1'}}),flush=True)"
        steps=[];result=discover([sys.executable,'-c',script],{},steps.append)
        self.assertEqual(steps,['checking_exit']);self.assertEqual(result['timezone'],'Etc/UTC')
    def test_hung_probe_is_bounded(self):
        script="import time;time.sleep(30)"
        with self.assertRaisesRegex(CreationFailure,'proxy_check_timeout'):discover([sys.executable,'-c',script],{},lambda _:None,timeout=.15)

if __name__=='__main__':unittest.main()

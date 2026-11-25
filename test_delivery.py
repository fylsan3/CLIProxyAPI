"""Focused failure checks for saved configuration and account-bound recovery."""
import hashlib,json,os,queue,sqlite3,sys,tempfile,threading,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'runtime-persistence/project'))
from saved_config import prepare
import portable_backup as backup

class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.state=Path(self.temp.name);self.state.chmod(0o700)
        self.key='a'*48;(self.state/'client-key').write_text(self.key);(self.state/'client-key').chmod(0o600)
        self.cfg={'host':'127.0.0.1','port':18317,'auth-dir':str(self.state/'auth-empty'),'api-keys':[self.key],
                  'remote-management':{'secret-key':self.key},'logging-to-file':True,'request-log':False}
        self.path=self.state/'config.yaml';self.save()
    def tearDown(self):self.temp.cleanup()
    def save(self):self.path.write_text(json.dumps(self.cfg));self.path.chmod(0o600)
    def test_native_config_preserved(self):
        before=self.path.read_bytes();self.assertEqual(prepare(ROOT,self.state)[3],18317);self.assertEqual(self.path.read_bytes(),before)
    def test_invalid_config_not_replaced(self):
        self.path.write_text('server: [');before=self.path.read_bytes()
        with self.assertRaises(ValueError):prepare(ROOT,self.state)
        self.assertEqual(self.path.read_bytes(),before)
    def test_missing_key_not_regenerated(self):
        (self.state/'client-key').unlink()
        with self.assertRaises(ValueError):prepare(ROOT,self.state)
        self.assertFalse((self.state/'client-key').exists())
    def test_body_limit_is_native_and_existing_config_is_not_rewritten(self):
        for limit in (0,524288):
            self.cfg['max-request-body-bytes']=limit;self.save();before=self.path.read_bytes()
            prepare(ROOT,self.state,max_request_body_bytes=limit)
            self.assertEqual(self.path.read_bytes(),before)
            with self.assertRaisesRegex(ValueError,'saved_body_limit_conflict'):prepare(ROOT,self.state,max_request_body_bytes=limit+1)
            self.assertEqual(self.path.read_bytes(),before)
    def test_port_override_rejected(self):
        before=self.path.read_bytes()
        with self.assertRaises(ValueError):prepare(ROOT,self.state,18318)
        self.assertEqual(self.path.read_bytes(),before)

class RestoreTests(unittest.TestCase):
    def test_backup_queue_survives_status_disk_failure(self):
        instance=backup.Packages.__new__(backup.Packages)
        instance.stopping=threading.Event();instance.lock=threading.Lock();instance.jobs=queue.Queue()
        instance.pending={'A','B'};instance.metadata_warnings=set();instance.folder=Path('/unused')
        for value in ('A','B',None):instance.jobs.put(value)
        called=[]
        def fail(owner):called.append(owner);raise OSError('test_disk_full')
        instance.export=fail
        with patch.object(backup,'write_json',side_effect=OSError('test_disk_full')):instance.run()
        self.assertEqual(called,['A','B']);self.assertEqual(instance.metadata_warnings,{'A','B'})

    def test_interrupted_card_database_commit_recovers(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);root.chmod(0o700);dbpath=root/'state.sqlite'
            old={'container':'a'*64};new={'container':'b'*64}
            backup.write_json(root/'A.json',new)
            backup.write_json(root/'restore-A.json',{'old':old,'new':new,'protection':{'phase':'ready'}})
            with sqlite3.connect(dbpath) as db:
                db.execute('CREATE TABLE bindings(owner TEXT,container TEXT)');db.execute("INSERT INTO bindings VALUES('A','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa')")
            started=[];control=SimpleNamespace(inspect=lambda c:{'State':{'Running':False}},card=lambda owner:root/'A.json',start=lambda owner:started.append(owner))
            instance=backup.Packages.__new__(backup.Packages);instance.folder=root
            instance.broker=SimpleNamespace(protection=SimpleNamespace(control=control,record=lambda owner:root/'protection-A.json'),connect=lambda:sqlite3.connect(dbpath))
            with patch.object(backup,'require_original_stopped'):
                self.assertTrue(instance.commit_restore('A'))
                self.assertFalse(instance.commit_restore('A'))
            with sqlite3.connect(dbpath) as db:self.assertEqual(db.execute("SELECT container FROM bindings WHERE owner='A'").fetchone()[0],'b'*64)
            self.assertEqual(started,['A']);self.assertFalse((root/'restore-A.json').exists())

    def test_old_credential_package_rejected_before_creating_volumes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);root.chmod(0o700)
            card={'container':'a'*64,'owner':'A','environment_id':'117a5ac8-69c0-4973-a9a0-b32ffcaec44f','image':'image','runtime':{},'network_config_sha256':'hash','network':'closed','backup':'existing'}
            data=b'ciphertext';(root/'test.cpab').write_bytes(data);(root/'test.cpab').chmod(0o600)
            receipt={'spec':{'card':card,'snapshot':'initial'},'file':'test.cpab','revision':1,'sha256':hashlib.sha256(data).hexdigest()}
            (root/'latest.json').write_text(json.dumps(receipt));(root/'latest.json').chmod(0o600)
            instance=backup.Packages.__new__(backup.Packages)
            backup.write_json(root/'A.json',card);instance.folder=root
            instance.broker=SimpleNamespace(protection=SimpleNamespace(control=SimpleNamespace(image='image',card=lambda owner:root/'A.json',inspect=lambda card:{'State':{'Running':False}})))
            backup.write_json(root/'credential-floor-A.json',{'revision':2})
            instance.target=lambda card:root
            with patch.object(backup,'docker',return_value='') as command:
                with self.assertRaisesRegex(ValueError,'backup_credentials_older_than_local'):instance.prepare_restore('A')
                self.assertEqual(command.call_count,2)
    def test_symlink_destination_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);root.chmod(0o700);(root/'actual').mkdir(mode=0o700);(root/'alias').symlink_to(root/'actual')
            with self.assertRaises(ValueError):backup.configure_destination(root,root/'alias')
            self.assertFalse((root/'backup-destination.json').exists())
    def test_wrong_destination_not_rebound(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);root.chmod(0o700);(root/'disk').mkdir(mode=0o700)
            backup.configure_destination(root,root/'disk');saved=(root/'backup-destination.json').read_bytes()
            (root/'disk/.destination.json').write_text('{"id":"different-disk"}')
            with self.assertRaises(ValueError):backup.configure_destination(root,root/'disk')
            self.assertEqual((root/'backup-destination.json').read_bytes(),saved)

if __name__=='__main__':unittest.main()

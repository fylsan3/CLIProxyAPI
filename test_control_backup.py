import json,os,secrets,sqlite3,tempfile,unittest
from pathlib import Path
import control_backup as backup
from lifecycle import Lease
from preflight import evaluate,MIN_HOST,MIN_ENGINE

class RecoveryTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='cpa-control-unit-',dir='/private/tmp');self.root=Path(self.tmp.name).resolve();self.root.chmod(0o700);self.state=self.root/'state';self.state.mkdir(mode=0o700);private=self.state/'broker-private';private.mkdir(mode=0o700)
  for name in backup.FIXED:
   p=self.state/name
   if name.endswith('.sqlite'):
    with sqlite3.connect(p) as db:db.execute('CREATE TABLE meta(scope TEXT)');db.execute("INSERT INTO meta VALUES('fictional')")
   else:p.write_bytes(secrets.token_bytes(32) if name.endswith('.key') else b'fictional-config-secret' if name=='client-key' else b'{}')
   p.chmod(0o600)
  self.key=self.root/'recovery.key';self.bundle=self.root/'control.cpactl'
 def tearDown(self):self.tmp.cleanup()
 def test_encrypted_roundtrip_same_path_without_overwrite(self):
  original={n:(self.state/n).read_bytes() for n in backup.FIXED if not n.endswith('.sqlite')}
  result=backup.export(self.state,self.bundle,self.key);self.assertTrue(result['verified']);self.assertNotIn(b'fictional-config-secret',self.bundle.read_bytes())
  self.state.rename(self.root/'retained-source')
  self.assertFalse(backup.restore(self.bundle,self.key,self.state)['starts_accounts'])
  self.assertEqual(original,{n:(self.state/n).read_bytes() for n in original})
  with self.assertRaisesRegex(ValueError,'destination_exists'):backup.restore(self.bundle,self.key,self.state)
 def test_wrong_key_and_tamper_leave_no_destination(self):
  backup.export(self.state,self.bundle,self.key);self.state.rename(self.root/'retained-source');wrong=self.root/'wrong.key';backup.create(wrong,secrets.token_bytes(32))
  with self.assertRaisesRegex(ValueError,'authentication_or_crypto'):backup.restore(self.bundle,wrong,self.state)
  self.assertFalse(self.state.exists());data=bytearray(self.bundle.read_bytes());data[-1]^=1;self.bundle.write_bytes(data)
  with self.assertRaisesRegex(ValueError,'authentication_or_crypto'):backup.restore(self.bundle,self.key,self.state)
  self.assertFalse(self.state.exists())
 def test_running_control_rejected_before_key_creation(self):
  lease=Lease(self.state/'launch.lock')
  try:
   with self.assertRaises(BlockingIOError):backup.export(self.state,self.bundle,self.key)
   self.assertFalse(self.key.exists());self.assertFalse(self.bundle.exists())
  finally:lease.close()
 def test_missing_key_is_not_regenerated_on_restore(self):
  backup.export(self.state,self.bundle,self.key);self.state.rename(self.root/'retained-source');self.key.unlink()
  with self.assertRaises(FileNotFoundError):backup.restore(self.bundle,self.key,self.state)
  self.assertFalse(self.key.exists());self.assertFalse(self.state.exists())
 def test_symlink_and_noncontrol_entries_rejected(self):
  target=self.root/'other';target.write_text('private');target.chmod(0o600);p=self.state/'client-key';p.unlink();p.symlink_to(target)
  with self.assertRaisesRegex(ValueError,'symlink'):backup.export(self.state,self.bundle,self.key)
  for name in ['../escape','/abs','broker-private/../../escape','broker-private/launch.log','broker-private/environments/../../escape.json']:
   self.assertFalse(backup.allowed(name))
 def test_pending_restore_rejected(self):
  p=self.state/'broker-private/restore-A.json';p.write_text('{}');p.chmod(0o600)
  with self.assertRaisesRegex(ValueError,'restore_in_progress'):backup.export(self.state,self.bundle,self.key)
 def test_changed_destination_path_rejected(self):
  backup.export(self.state,self.bundle,self.key)
  with self.assertRaisesRegex(ValueError,'path_mismatch'):backup.restore(self.bundle,self.key,self.root/'different')
  self.assertFalse((self.root/'different').exists())
 def test_startup_excludes_restore_and_preserves_existing_state(self):
  before=(self.state/'client-key').read_bytes();gate=Lease(self.state.parent/('.'+self.state.name+'.restore.lock'))
  try:
   with self.assertRaises(BlockingIOError):backup.startup_lease(self.state)
  finally:gate.close()
  lease=backup.startup_lease(self.state)
  try:
   self.assertEqual((self.state/'client-key').read_bytes(),before)
   with self.assertRaises(BlockingIOError):backup.export(self.state,self.bundle,self.key)
  finally:lease.close()
 def test_capacity_thresholds(self):
  self.assertTrue(evaluate(MIN_HOST,MIN_HOST,MIN_ENGINE)['ready'])
  self.assertEqual(evaluate(MIN_HOST-1,MIN_HOST-1,MIN_ENGINE-1)['issues'],['control_disk_low','backup_disk_low','container_disk_low'])

if __name__=='__main__':unittest.main()

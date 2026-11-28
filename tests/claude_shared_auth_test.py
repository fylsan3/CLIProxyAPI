import json,os,sys,tempfile,time,unittest
from pathlib import Path
from datetime import datetime,timezone
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'image'))
import claude_shared_auth as shared
import claude_code as cli

class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.path=self.root/'native-auth.json'
  self.env=patch.dict(os.environ,{'FIXTURE_OWNER':'A'},clear=True);self.env.start()
  self.file=patch.object(shared,'AUTH_FILE',self.path);self.file.start()
  self.value={'owner':'A','revision':1,'token':{'access_token':'fixture-access-1','refresh_token':'fixture-refresh-secret','expired':datetime.fromtimestamp(time.time()+14400,timezone.utc).isoformat()}}
  self.save()
 def save(self):self.path.write_text(json.dumps(self.value));self.path.chmod(0o600)
 def tearDown(self):self.file.stop();self.env.stop();self.tmp.cleanup()
 def test_only_access_token_is_given_to_cli(self):
  snapshot=shared.snapshot()
  with patch.object(cli,'ROOT',self.root/'cli'):
   env=cli.environment(snapshot)
   self.assertEqual(env['CLAUDE_CODE_OAUTH_TOKEN'],'fixture-access-1')
   self.assertNotIn('fixture-refresh-secret',json.dumps(env));self.assertNotIn('fixture-access-1',repr(snapshot))
   self.assertNotIn('fixture-access-1',json.dumps(shared.status()))
 def test_new_call_reads_new_atomic_revision(self):
  previous=shared.snapshot();self.value['revision']=2;self.value['token']['access_token']='fixture-access-2';self.save()
  self.assertEqual(shared.snapshot().revision,2);self.assertEqual(previous.revision,1)
 def test_expired_is_not_refreshed_or_rewritten(self):
  self.value['token']['expired']='2000-01-01T00:00:00Z';self.save();before=self.path.read_bytes()
  self.assertEqual(shared.status()['error'],'waiting_for_go_refresh');self.assertEqual(self.path.read_bytes(),before)
 def test_other_account_and_disabled_are_rejected(self):
  self.value['owner']='B';self.save();self.assertEqual(shared.status()['error'],'shared_auth_account_mismatch')
  self.value['owner']='A';self.value['auth']={'disabled':True};self.save();self.assertEqual(shared.status()['error'],'go_account_disabled')
 def test_rejected_access_is_not_reused(self):
  self.value['renewal']={'rejected_access_token':self.value['token']['access_token']};self.save()
  self.assertEqual(shared.status()['error'],'shared_access_token_rejected')
 def test_refresh_problem_does_not_discard_still_valid_access(self):
  self.value['renewal']={'requires_sign_in':True};self.save();self.assertTrue(shared.status()['ready'])
  self.assertTrue(shared.status()['requires_sign_in'])
 def test_unsafe_permissions_and_symlinks(self):
  self.path.chmod(0o644);self.assertFalse(shared.status()['ready']);self.path.unlink()
  other=self.root/'other';other.write_text(json.dumps(self.value));self.path.symlink_to(other)
  self.assertFalse(shared.status()['ready'])
 def test_existing_independent_cli_login_is_preserved_and_blocked(self):
  directory=self.root/'cli';directory.mkdir();file=directory/'.credentials.json';file.write_text('{"claudeAiOauth":{"refreshToken":"other"}}');file.chmod(0o600)
  self.assertEqual(shared.status(directory)['error'],'separate_claude_login_present');self.assertTrue(file.exists())
 def test_independent_login_action_is_disabled(self):
  service=cli.Service.__new__(cli.Service)
  with self.assertRaisesRegex(ValueError,'use_go_authorization'):service.start_terminal({'mode':'login'})
  with self.assertRaisesRegex(ValueError,'use_go_authorization'):service.dispatch({'op':'browser-open','url':'https://claude.ai/oauth/authorize'})

if __name__=='__main__':unittest.main()

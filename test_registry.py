"""Account registration must never replace an existing environment or accept unsafe names."""
import concurrent.futures,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from account_registry import Registry
from account_identity import owner_for,valid_owner

class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.root.chmod(0o700);self.registry=Registry(self.root)
    def tearDown(self):self.temp.cleanup()
    def test_empty_registry_and_non_ab_identity_survive_restart(self):
        self.assertEqual(self.registry.owners(),[])
        row=self.registry.register('research-03','研发账号','mock-claude')
        self.assertEqual(Registry(self.root).get('research-03'),row)
        self.assertEqual(self.registry.owners(),['RESEARCH-03'])
    def test_identical_registration_is_idempotent(self):
        first=self.registry.register('research-03','研发账号','mock-claude');before=self.registry.path.read_bytes()
        self.assertEqual(self.registry.register('research-03','研发账号','mock-claude'),first)
        self.assertEqual(self.registry.path.read_bytes(),before)
    def test_conflicting_duplicate_never_overwrites(self):
        self.registry.register('research-03','原账号','mock-claude');before=self.registry.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'account_already_registered'):self.registry.register('research-03','另一个账号','mock-claude')
        self.assertEqual(self.registry.path.read_bytes(),before)
    def test_same_display_name_keeps_distinct_accounts(self):
        for slug in ('left-team','right-team'):self.registry.register(slug,'研发','mock-claude')
        self.assertEqual(self.registry.owners(),['LEFT-TEAM','RIGHT-TEAM'])
    def test_unsafe_identifiers_do_not_write(self):
        before=self.registry.path.read_bytes()
        for slug in ('../a','a/b','A','a.','a-','é','a\n','a'*33,0,None,''):
            with self.subTest(slug=slug),self.assertRaises(ValueError):self.registry.register(slug,'test','mock-claude')
        self.assertEqual(self.registry.path.read_bytes(),before)
    def test_unknown_provider_rejected(self):
        before=self.registry.path.read_bytes()
        with self.assertRaisesRegex(ValueError,'provider_not_available'):self.registry.register('real','test','nonexistent-provider')
        self.assertEqual(self.registry.path.read_bytes(),before)
    def test_corrupt_registry_not_reset(self):
        self.registry.path.write_text('{invalid');before=self.registry.path.read_bytes()
        with self.assertRaises(ValueError):Registry(self.root)
        self.assertEqual(self.registry.path.read_bytes(),before)
    def test_missing_registry_with_account_files_not_reset(self):
        self.registry.path.unlink();(self.root/'environments').mkdir(mode=0o700)
        (self.root/'environments/RESEARCH-03.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'account_registry_missing_no_reset'):Registry(self.root)
        self.assertFalse(self.registry.path.exists())
    def test_parallel_registration_does_not_lose_rows(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda n:self.registry.register('job-'+str(n),'研发','mock-claude'),range(12)))
        self.assertEqual(len(Registry(self.root).list()),12)
    def test_failed_commit_leaves_previous_registry(self):
        before=self.registry.path.read_bytes()
        with patch('account_registry.write_json',side_effect=OSError('test disk full')):
            with self.assertRaises(OSError):self.registry.register('new','研发','mock-claude')
        self.assertEqual(self.registry.path.read_bytes(),before)
    def test_changed_provider_backup_rejected_before_restore(self):
        from types import SimpleNamespace
        import portable_backup as backup
        card={'owner':'RESEARCH-03','image':'image','account_definition':{'slug':'research-03','owner':'RESEARCH-03','provider':'mock-claude'}}
        backup.write_json(self.root/'RESEARCH-03.json',card)
        wrong=dict(card,account_definition=dict(card['account_definition'],provider='different-provider'))
        backup.write_json(self.root/'latest.json',{'spec':{'card':wrong}})
        control=SimpleNamespace(image='image',card=lambda _:self.root/'RESEARCH-03.json')
        instance=backup.Packages.__new__(backup.Packages)
        instance.broker=SimpleNamespace(protection=SimpleNamespace(control=control));instance.target=lambda _:self.root
        with patch.object(backup,'require_original_stopped'),patch.object(backup,'docker') as docker:
            with self.assertRaisesRegex(ValueError,'backup_card_changed'):instance.prepare_restore('RESEARCH-03')
            docker.assert_not_called()

if __name__=='__main__':unittest.main()

"""Rollback entrypoint guards, using temporary files and a mocked service switch."""
import json
import plistlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import mac_release as release


class RollbackGuards(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.user = Path(self.temp.name)
        self.home = self.user / 'installation'
        self.state = self.home / 'state'
        self.transaction = self.home / 'transaction'
        self.plist = self.user / 'service.plist'
        for directory in (self.state / 'broker-private', self.transaction,
                          self.home / 'legacy-backup', self.user / 'cliproxyapi/bin'):
            directory.mkdir(parents=True)
        self.home.chmod(0o700)
        self.registry = self.state / 'broker-private/accounts.json'
        self.registry.write_text('{"accounts": {}}')
        self.plist.write_bytes(plistlib.dumps({'WorkingDirectory': str(self.state)}))
        (self.transaction / 'switch.json').write_text(json.dumps({'plist': str(self.plist)}))
        for name in ('config.yaml', 'bin/cli-proxy-api'):
            (self.user / 'cliproxyapi' / name).write_text('fictional old file')
        (self.home / 'legacy-backup/digests.json').write_text(json.dumps({
            'config': release.digest(self.user / 'cliproxyapi/config.yaml'),
            'binary': release.digest(self.user / 'cliproxyapi/bin/cli-proxy-api')}))
        self.record = self.home / 'deployment.json'
        self.record.write_text(json.dumps({'state': str(self.state),
            'transaction': str(self.transaction), 'port': 12345, 'deployed': True}))

    def invoke(self):
        with patch.object(Path, 'home', return_value=self.user):
            release.rollback(self.home)

    def test_accounts_prevent_automatic_rollback(self):
        self.registry.write_text('{"accounts": {"A": {"fictional": true}}}')
        with patch.object(release, 'Switch') as switch:
            with self.assertRaisesRegex(ValueError, 'accounts_exist'):
                self.invoke()
            switch.assert_not_called()

    def test_wrong_service_is_not_stopped(self):
        self.plist.write_bytes(plistlib.dumps({'WorkingDirectory': 'another-service'}))
        with patch.object(release, 'Switch') as switch:
            with self.assertRaisesRegex(ValueError, 'active_service_does_not_match'):
                self.invoke()
            switch.assert_not_called()

    def test_modified_old_program_is_not_started(self):
        (self.user / 'cliproxyapi/bin/cli-proxy-api').write_text('modified')
        with patch.object(release, 'Switch') as switch:
            with self.assertRaisesRegex(ValueError, 'legacy_files_changed'):
                self.invoke()
            switch.assert_not_called()

    def test_empty_account_rollback_preserves_state(self):
        with patch.object(release, 'Switch') as switch, patch.object(release, 'request', return_value=(200, b'')):
            switch.return_value.restore.side_effect = lambda check: self.assertTrue(check())
            self.invoke()
            switch.return_value.restore.assert_called_once()
        record = json.loads(self.record.read_text())
        self.assertFalse(record['deployed'])
        self.assertTrue(record['rolled_back'])
        self.assertTrue(self.registry.is_file())


if __name__ == '__main__':
    unittest.main()

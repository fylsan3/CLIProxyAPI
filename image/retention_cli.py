"""Private lifecycle commands for explicitly bound, offline A/B test accounts."""
import glob
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

from retention import RetentionError, binding, digest, read_json, retained, write_json, atomic, offline_network, private


def network_copy(root, initialize=False):
    source = Path('/network-config/config.json')
    private(source)
    raw = source.read_bytes()
    if hashlib.sha256(raw).hexdigest() != os.environ['PROXY_CONFIG_SHA256']:
        raise RetentionError('network_config_binding_mismatch')
    target = root / 'network-config.json'
    if initialize:
        if target.exists() or target.is_symlink():
            raise RetentionError('network_copy_already_exists')
        atomic(target, raw)
    private(target)
    if target.read_bytes() != raw:
        raise RetentionError('saved_network_config_mismatch')


def runtime_inventory():
    offline_network()
    chrome = sorted(glob.glob('/ms-playwright/chromium-*/chrome-linux*/chrome'))
    if len(chrome) != 1:
        raise RetentionError('browser_version_ambiguous')
    return {'architecture': platform.machine(), 'os_release_sha256': digest(Path('/etc/os-release')),
            'browser_sha256': digest(Path(chrome[0])), 'worker_sha256': digest(Path('/opt/native/worker')),
            'timezone': os.environ.get('TZ', ''), 'locale': os.environ.get('LANG', ''),
            'locale_all': os.environ.get('LC_ALL', ''), 'language': os.environ.get('LANGUAGE', '')}


def expected_binding():
    inventory = runtime_inventory()
    if inventory != json.loads(os.environ['EXPECTED_RUNTIME']):
        raise RetentionError('runtime_changed')
    return binding(os.environ['FIXTURE_OWNER'], os.environ['ENVIRONMENT_ID'], inventory)


def verify_backups(store):
    store.verify_snapshot(Path('/backup/initial'))
    if read_json(Path('/backup/credentials/binding.json')) != store.expected:
        raise RetentionError('credential_backup_binding_mismatch')


def restore_credentials(store, path=Path('/backup/credentials/latest.json')):
    if not path.exists():
        if (store.root / 'native-auth.json').exists():
            raise RetentionError('credential_checkpoint_missing')
        return
    latest = read_json(path)
    if latest['environment_id'] != store.expected['environment_id'] or latest['record']['owner'] != store.expected['owner']:
        raise RetentionError('credential_checkpoint_binding_mismatch')
    current = store.root / 'native-auth.json'
    if current.exists() and read_json(current)['revision'] > latest['record']['revision']:
        raise RetentionError('credential_checkpoint_older')
    write_json(current, latest['record'])


def reconcile_checkpoint(store):
    current = store.root / 'native-auth.json'
    checkpoint = Path('/backup/credentials/latest.json')
    if not current.exists():
        if checkpoint.exists():
            raise RetentionError('credential_primary_missing')
        return
    record = read_json(current)
    if record['owner'] != store.expected['owner']:
        raise RetentionError('credential_owner_mismatch')
    expected = {'environment_id': store.expected['environment_id'], 'record': record}
    if checkpoint.exists():
        saved = read_json(checkpoint)
        if saved['environment_id'] != expected['environment_id'] or saved['record']['owner'] != record['owner']:
            raise RetentionError('credential_checkpoint_binding_mismatch')
        if saved['record']['revision'] > record['revision']:
            raise RetentionError('primary_credential_older')
        if saved == expected:
            return
    # The primary committed file is authoritative during ordinary restart.
    # Repair an interrupted second write without contacting any provider.
    write_json(checkpoint, expected)


def run():
    action = sys.argv[1]
    if action == 'inventory':
        print(json.dumps(runtime_inventory(), sort_keys=True))
        return
    with retained('/state', expected_binding()) as store:
        if action == 'initialize':
            backup = Path('/backup')
            if list(backup.iterdir()):
                raise RetentionError('backup_not_empty')
            store.initialize()
            network_copy(store.root, initialize=True)
            (backup / 'credentials').mkdir(mode=0o700)
            write_json(backup / 'credentials/binding.json', store.expected)
            store.snapshot(backup, 'initial')
        elif action == 'snapshot':
            network_copy(store.root)
            verify_backups(store)
            store.snapshot('/backup', sys.argv[2])
        elif action == 'restore':
            # Both backups must be checked before touching the empty destination.
            verify_backups(store)
            store.restore(Path('/backup') / sys.argv[2], finalize=False)
            network_copy(store.root)
            write_json(store.root / 'restore-in-progress.json', {'phase': 'credentials'})
            restore_credentials(store)
            (store.root / 'restore-in-progress.json').unlink()
            from retention import syncdir
            syncdir(store.root)
        elif action == 'check':
            store.validate()
            network_copy(store.root)
            verify_backups(store)
            reconcile_checkpoint(store)
        else:
            raise RetentionError('unknown_action')
        print(json.dumps({'ok': True, 'action': action, 'owner': store.expected['owner'], 'environment_id': store.expected['environment_id']}))


if __name__ == '__main__':
    try:
        run()
    except (RetentionError, OSError, ValueError, KeyError):
        # File paths and account content are deliberately not printed.
        print(json.dumps({'ok': False, 'error': 'environment_protection_failed'}))
        sys.exit(1)

"""Onboarding backup gate around the existing isolated CPA worker lifecycle."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parent
from network_control import Control, DOCKER, docker
from retention import read_json, write_json
# Dependencies extend sys.path; keep this candidate first for its panel and assets.
sys.path.insert(0, str(ROOT))


class Protection:
    def __init__(self, folder):
        self.control = Control(folder)
        self.locks = {}
        self.locks_guard=threading.Lock()

    def lock_for(self,owner):
        self.control.registry.get(owner.lower())
        with self.locks_guard:return self.locks.setdefault(owner,threading.Lock())

    def record(self, owner):
        return self.control.folder / ('protection-' + owner + '.json')

    def state(self, owner):
        path = self.record(owner)
        return read_json(path) if path.exists() else {'phase': 'not_created', 'backup_verified': False}

    def phase(self, owner, phase, **values):
        record = dict(self.state(owner), phase=phase, updated_at=int(time.time()), **values)
        write_json(self.record(owner), record)
        return record

    def create(self, owner, proxy_url):
        from creation_progress import CreationFailure, safe_error, STEPS
        with self.lock_for(owner):
            self.phase(owner, 'creating', backup_verified=False, creation_steps=[], creation_error=None,
                       creation_started_at=int(time.time()), creation_finished_at=None)
            current='checking_socks'
            def progress(step):
                nonlocal current
                if step not in STEPS:raise ValueError('invalid_creation_step')
                current=step;record=self.state(owner);steps=record.get('creation_steps',[])
                stamp=int(time.time())
                if steps and steps[-1]['status']=='running':steps[-1].update(status='completed',finished_at=stamp)
                steps.append({'step':step,'status':'running','started_at':stamp})
                self.phase(owner,'creating',creation_steps=steps[-len(STEPS):])
            try:
                card = self.control.create(owner, proxy_url, progress=progress)
                steps=self.state(owner)['creation_steps']
                if steps:steps[-1].update(status='completed',finished_at=int(time.time()))
                self.phase(owner, 'awaiting_authorization', initial_backup=True,
                           environment_id=card['environment_id'],creation_steps=steps,creation_finished_at=int(time.time()))
                return card
            except BaseException as error:
                code=safe_error(error,current);steps=self.state(owner).get('creation_steps',[])
                if not steps:steps=[{'step':current,'status':'running','started_at':int(time.time())}]
                steps[-1].update(status='failed',finished_at=int(time.time()))
                self.phase(owner, 'creation_failed', creation_steps=steps,creation_error=code,creation_finished_at=int(time.time()))
                print(json.dumps({'event':'account_creation_failed','owner':owner,'step':current,'code':code}),flush=True)
                if isinstance(error,(KeyboardInterrupt,SystemExit)):raise
                raise CreationFailure(code) from None

    def recover_creation(self, owner):
        record=self.state(owner)
        if record.get('phase')!='creating':return
        steps=record.get('creation_steps',[])
        if steps and steps[-1].get('status')=='running':steps[-1].update(status='failed',finished_at=int(time.time()))
        self.phase(owner,'creation_failed',creation_steps=steps,creation_error='creation_interrupted',creation_finished_at=int(time.time()))

    def browser_closed(self, card):
        result = subprocess.run([*DOCKER, 'exec', '--user', '1001:1001', '-i', card['container'], 'python3', '-B',
                                 '/opt/sample/worker.py', 'request'], input='{"op":"close-browser"}\n',
                                text=True, capture_output=True, timeout=20, check=True)
        state = json.loads(result.stdout)
        if state.get('browser') is not False or state.get('error'):
            raise ValueError('browser_close_failed')

    def verify(self, card, name):
        # The worker is stopped; the helper must acquire its exclusive lease.
        script = """import json,sys
sys.path.insert(0,'/opt/native')
from retention import retained,digest
from retention_cli import expected_binding
from pathlib import Path
with retained('/state',expected_binding()) as store:
 store.validate()
 path=Path('/backup')/sys.argv[1]
 store.verify_snapshot(path)
 print(json.dumps({'verified':True,'manifest_sha256':digest(path/'manifest.json')}))
"""
        raw = docker('run', '--rm', *self.control.args(card), '--entrypoint', 'python3',
                     card['image'], '-B', '-c', script, name)
        return json.loads(raw)['manifest_sha256']

    def complete_backup(self, owner, health):
        # The caller owns the per-account operation lock.
        card = self.control.load(owner)
        info = self.control.inspect(card)
        if not info['State']['Running']:
            self.control.start(owner)
        for _ in range(100):
            try:
                state = health()
                if state.get('authorized'):
                    break
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
            time.sleep(.1)
        else:
            raise ValueError('saved_authorization_unavailable')
        if state.get('active_calls'):
            raise ValueError('account_has_active_calls')
        self.phase(owner, 'closing_browser', backup_verified=False)
        self.browser_closed(card)
        self.phase(owner, 'saving_backup', browser_closed=True)
        docker('stop', '-t', '15', card['container'])
        name = 'after-authorization-' + uuid.uuid4().hex
        try:
            self.control.helper(card, 'snapshot', name)
            self.phase(owner, 'verifying_backup', snapshot=name)
            manifest_hash = self.verify(card, name)
            self.phase(owner, 'starting_protected_environment')
            self.control.start(owner)
            for _ in range(100):
                try:
                    if health().get('authorized'):
                        break
                except (OSError, ValueError, subprocess.SubprocessError):
                    pass
                time.sleep(.1)
            else:
                raise ValueError('protected_worker_not_ready')
            return self.phase(owner, 'ready', backup_verified=True, snapshot=name,
                              manifest_sha256=manifest_hash, verified_at=int(time.time()),
                              local_backup_only=True, off_host_verified=False)
        except BaseException:
            self.phase(owner, 'backup_failed', backup_verified=False)
            raise

    def manifest_available(self, owner, info):
        record = self.state(owner)
        if record.get('phase') != 'ready' or not record.get('backup_verified'):
            return False
        if not info['State']['Running']:
            return False
        # Hash only the committed manifest on each dispatch; full file verification
        # happens before admission and on managed restart.
        script = "from pathlib import Path;import hashlib,sys;print(hashlib.sha256((Path('/backup')/sys.argv[1]/'manifest.json').read_bytes()).hexdigest())"
        actual = docker('exec', '--user', '1001:1001', info['Id'], 'python3', '-c', script, record['snapshot'], timeout=4)
        return actual == record.get('manifest_sha256')

    def restart(self, owner):
        with self.lock_for(owner):
            card = self.control.load(owner)
            self.control.inspect(card)
            previous = self.state(owner)
            self.phase(owner, 'checking_restore', backup_verified=False)
            docker('stop', '-t', '15', card['container'])
            try:
                if previous.get('snapshot'):
                    digest = self.verify(card, previous['snapshot'])
                    if digest != previous.get('manifest_sha256'):
                        raise ValueError('backup_manifest_changed')
                self.control.start(owner)
                write_json(self.record(owner), previous)
            except BaseException:
                self.phase(owner, 'recovery_check_failed', backup_verified=False)
                raise

    def close(self):
        self.control.close()

"""On-demand remote desktop and automatic post-callback admission."""
import json
import subprocess
import threading
import time

from relay import Relay


class Browsers:
    def __init__(self, broker, cli):
        self.broker, self.cli = broker, cli
        self.relays = {}
        self.sessions = {}
        self.lock = threading.RLock()

    def recover(self):
        # Reconnect control-plane observation; never restart provider authorization.
        for owner in self.broker.registry.owners():
            phase = self.broker.protection.state(owner).get('phase')
            if phase not in ('authorizing', 'exchanging_credentials'):
                continue
            event = threading.Event()
            self.sessions[owner] = event
            threading.Thread(target=self.watch, args=(owner, event), daemon=True).start()

    def command(self, owner, op, **args):
        info = self.broker.inspect(owner)
        if not info or not info['State']['Running']:
            raise ValueError('container_unavailable')
        result = subprocess.run([*self.cli, 'exec', '--user', '1001:1001', '-i', info['Id'],
                                 'python3', '-B', '/opt/sample/worker.py', 'request'],
                                input=json.dumps(dict(op=op, **args)), text=True, capture_output=True,
                                timeout=25, check=True)
        value = json.loads(result.stdout)
        if value.get('error') in ('browser_sandbox_unavailable','browser_start_failed','authorization_url_rejected','browser_restore_unavailable'):
            raise ValueError(value['error'])
        if value.get('error') or value.get('owner') != owner or value.get('host') != info['Config']['Hostname']:
            raise ValueError('browser_operation_failed')
        return info, value

    def open(self, owner, url=None):
        with self.lock:
            info, value = self.command(owner, 'open-browser', **({'url': url} if url else {}))
            session = value['desktop_session']
            def guard():
                actual, status = self.command(owner, 'status')
                if actual['Id'] != info['Id'] or not status['browser'] or status['desktop_session'] != session:
                    raise ValueError('desktop_session_changed')
            relay = self.relays.get(owner)
            if not relay or relay.session != session:
                if relay:
                    relay.close()
                relay = Relay(self.cli, info['Id'], session, guard, lambda: self.command(owner,'restore-browser'))
                self.relays[owner] = relay
            return {'viewer_url': relay.url+'#'+value['desktop_pass'], 'browser': True}

    def close(self, owner):
        with self.lock:
            relay = self.relays.pop(owner, None)
            if relay:
                relay.close()
            self.command(owner, 'close-browser')

    def begin(self, owner):
        with self.lock:
            if owner in self.sessions:
                raise ValueError('authorization_pending')
            code, pending = self.broker.invoke(owner, '/auth/begin', {})
            if code != 200:
                return code, pending
            try:
                result = self.open(owner, pending['authorization_url'])
            except Exception:
                try:
                    self.broker.invoke(owner, '/auth/cancel', {})
                finally:
                    self.broker.protection.phase(owner, 'authorization_failed', backup_verified=False)
                raise
            cancelled = threading.Event()
            self.sessions[owner] = cancelled
            threading.Thread(target=self.watch, args=(owner, cancelled), daemon=True).start()
            return 200, result

    def watch(self, owner, cancelled):
        authorized = False
        try:
            deadline = time.monotonic()+610
            while not self.broker.stopping.is_set() and not cancelled.wait(.3):
                if time.monotonic() > deadline:
                    break
                try:
                    code, status = self.broker.invoke(owner, '/health', {})
                except (OSError, ValueError, subprocess.SubprocessError):
                    continue
                if code != 200:
                    continue
                if status.get('authorized'):
                    authorized = True
                    self.close(owner)
                    self.broker.finalize_authorization(owner, {})
                    return
                if status.get('authorization_issue') or not status.get('authorization_pending'):
                    break
            if not self.broker.stopping.is_set():
                self.close(owner)
                self.broker.protection.phase(owner, 'authorization_failed', backup_verified=False)
        except (OSError, ValueError, subprocess.SubprocessError):
            # Retain committed credentials and expose the existing backup retry action.
            self.broker.protection.phase(owner, 'backup_failed' if authorized else 'authorization_failed',
                                         backup_verified=False)
        finally:
            with self.lock:
                if self.sessions.get(owner) is cancelled:
                    self.sessions.pop(owner, None)

    def cancel(self, owner):
        with self.lock:
            event = self.sessions.get(owner)
            if event:
                event.set()
            result = self.broker.invoke(owner, '/auth/cancel', {})
            self.close(owner)
            return result

    def shutdown(self):
        with self.lock:
            for event in self.sessions.values():
                event.set()
            for relay in self.relays.values():
                relay.close()
            self.relays.clear()

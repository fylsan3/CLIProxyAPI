"""Fail-closed retention for offline account data; never manufactures device identity."""
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import socket
import stat
import tempfile
import uuid


class RetentionError(ValueError):
    pass


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def syncdir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def private(path, directory=False):
    info = path.lstat()
    good_type = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not good_type or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise RetentionError('unsafe_storage')
    if not directory and info.st_nlink != 1:
        raise RetentionError('unsafe_storage')


def atomic(path, data):
    fd, name = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        syncdir(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def write_json(path, value):
    atomic(path, json.dumps(value, sort_keys=True).encode())


def copy_committed(source, target, executable=False):
    fd, name = tempfile.mkstemp(prefix='.pending-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as out, source.open('rb') as inp:
            shutil.copyfileobj(inp, out, 1024 * 1024)
            os.fchmod(out.fileno(), 0o700 if executable else 0o600)
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, target)
        syncdir(target.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def read_json(path):
    private(path)
    try:
        return json.loads(path.read_text())
    except (ValueError, UnicodeError):
        raise RetentionError('record_invalid') from None


def offline_network():
    if {name for _, name in socket.if_nameindex()} != {'lo'}:
        raise RetentionError('network_not_isolated')


def binding(owner, environment_id, runtime):
    if owner not in ('A', 'B') or str(uuid.UUID(environment_id)) != environment_id:
        raise RetentionError('test_binding_invalid')
    return {'schema': 1, 'owner': owner, 'environment_id': environment_id, 'runtime': runtime}


class Store:
    def __init__(self, root, expected, network_check=offline_network):
        # Do this before touching any account disk or credential.
        network_check()
        self.root, self.expected = Path(root), expected
        private(self.root, directory=True)
        fd = os.open(self.root / '.retention.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        self.lock = os.fdopen(fd, 'rb')
        try:
            private(self.root / '.retention.lock')
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            self.close()
            raise RetentionError('environment_in_use') from None

    def close(self):
        if self.lock is not None:
            self.lock.close()
            self.lock = None

    def empty(self):
        return not any(p.name != '.retention.lock' for p in self.root.iterdir())

    def initialize(self):
        if not self.empty():
            raise RetentionError('refuse_reinitialize_existing_environment')
        # A separate explicit creation operation is the only initializer.
        for name in ('chromium-profile', 'desktop-home'):
            (self.root / name).mkdir(mode=0o700)
        write_json(self.root / 'environment.json', {'schema': 1, 'owner': self.expected['owner']})
        write_json(self.root / 'retention.json', self.expected)
        syncdir(self.root)

    def validate(self):
        if (self.root / 'restore-in-progress.json').exists():
            raise RetentionError('restore_incomplete')
        if not (self.root / 'retention.json').exists():
            raise RetentionError('environment_missing_no_auto_create')
        if read_json(self.root / 'retention.json') != self.expected:
            raise RetentionError('environment_binding_or_runtime_mismatch')
        if read_json(self.root / 'environment.json') != {'schema': 1, 'owner': self.expected['owner']}:
            raise RetentionError('browser_owner_mismatch')
        for name in ('chromium-profile', 'desktop-home'):
            private(self.root / name, directory=True)

    def snapshot(self, backups, name):
        self.validate()
        backups = Path(backups)
        private(backups, directory=True)
        if self.root.resolve() == backups.resolve() or self.root.resolve() in backups.resolve().parents:
            raise RetentionError('backup_must_be_separate')
        if not name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in name):
            raise RetentionError('snapshot_name_invalid')
        final = backups / name
        if final.exists() or final.is_symlink():
            raise RetentionError('snapshot_already_exists')
        staging = Path(tempfile.mkdtemp(prefix='.pending-', dir=backups))
        try:
            data = staging / 'data'
            data.mkdir(mode=0o700)
            files, directories = {}, []
            for path in sorted(self.root.rglob('*')):
                rel = path.relative_to(self.root).as_posix()
                if rel in ('.retention.lock', 'profile.lock'):
                    continue
                if rel in ('chromium-profile/SingletonLock', 'chromium-profile/SingletonSocket', 'chromium-profile/SingletonCookie') and path.is_symlink():
                    continue
                info = path.lstat()
                target = data / rel
                if stat.S_ISDIR(info.st_mode):
                    if info.st_uid != os.getuid():
                        raise RetentionError('snapshot_owner_mismatch')
                    target.mkdir(mode=0o700)
                    directories.append(rel)
                elif stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1:
                    executable = bool(info.st_mode & stat.S_IXUSR)
                    copy_committed(path, target, executable)
                    files[rel] = {'sha256': digest(target), 'bytes': target.stat().st_size, 'executable': executable}
                else:
                    raise RetentionError('snapshot_unsafe_entry')
            manifest = {'binding': self.expected, 'files': files, 'directories': directories}
            write_json(staging / 'manifest.json', manifest)
            for directory in sorted(data.rglob('*'), reverse=True):
                if directory.is_dir():
                    syncdir(directory)
            syncdir(data)
            syncdir(staging)
            os.rename(staging, final)
            syncdir(backups)
            return manifest
        finally:
            if staging.exists():
                shutil.rmtree(staging)

    def verify_snapshot(self, snapshot):
        snapshot = Path(snapshot)
        private(snapshot, directory=True)
        manifest = read_json(snapshot / 'manifest.json')
        if manifest['binding'] != self.expected:
            raise RetentionError('snapshot_binding_or_runtime_mismatch')
        data = snapshot / 'data'
        private(data, directory=True)
        for rel in [*manifest['files'], *manifest['directories']]:
            parts = PurePosixPath(rel)
            if not rel or parts.is_absolute() or '..' in parts.parts or str(parts) != rel:
                raise RetentionError('snapshot_path_invalid')
            for parent in (data / rel).parents:
                if parent == data:
                    break
                private(parent, directory=True)
        for rel in manifest['directories']:
            private(data / rel, directory=True)
        for rel, details in manifest['files'].items():
            path = data / rel
            private(path)
            if path.stat().st_size != details['bytes'] or digest(path) != details['sha256']:
                raise RetentionError('snapshot_checksum_mismatch')
        if read_json(data / 'retention.json') != self.expected:
            raise RetentionError('snapshot_record_mismatch')
        return manifest

    def restore(self, snapshot, finalize=True):
        if not self.empty():
            raise RetentionError('refuse_restore_over_existing_environment')
        snapshot = Path(snapshot)
        manifest = self.verify_snapshot(snapshot)
        # A crash leaves this durable marker; startup then refuses partial state.
        write_json(self.root / 'restore-in-progress.json', {'snapshot': snapshot.name})
        for rel in sorted(manifest['directories'], key=lambda p: len(PurePosixPath(p).parts)):
            (self.root / rel).mkdir(mode=0o700)
        for rel in manifest['files']:
            copy_committed(snapshot / 'data' / rel, self.root / rel, manifest['files'][rel].get('executable', False))
        if finalize:
            (self.root / 'restore-in-progress.json').unlink()
            syncdir(self.root)
            self.validate()


@contextlib.contextmanager
def retained(root, expected, network_check=offline_network):
    store = Store(root, expected, network_check)
    try:
        yield store
    finally:
        store.close()

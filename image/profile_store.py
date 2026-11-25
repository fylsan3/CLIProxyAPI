"""Persist actual Chromium state for one offline worker. No identity spoofing."""
import fcntl
import json
import os
from pathlib import Path
import socket
import stat
import tempfile


class ProfileError(ValueError):
    pass


def offline_network_check():
    from network_gate import check
    try: check()
    except (OSError,ValueError,KeyError): raise ProfileError('account_proxy_unavailable') from None


def directory(path):
    path.mkdir(mode=0o700, exist_ok=True)
    info=path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid():
        raise ProfileError('profile_storage_unsafe')


def regular(path):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1:
        raise ProfileError('profile_storage_unsafe')


def atomic_json(path, value):
    if path.exists() or path.is_symlink(): regular(path)
    fd,temp=tempfile.mkstemp(dir=path.parent,prefix='.pending-')
    try:
        with os.fdopen(fd,'w') as out:
            json.dump(value,out);out.flush();os.fsync(out.fileno())
        os.replace(temp,path)
        fd=os.open(path.parent,os.O_RDONLY)
        try:os.fsync(fd)
        finally:os.close(fd)
    finally:
        if os.path.exists(temp):os.unlink(temp)


class ProfileStore:
    def __init__(self, root, owner, network_check=offline_network_check):
        self.root=Path(root);self.owner=owner;self.network_check=network_check;self.lock=None
        self.network_check()  # Deliberately before any persistent account state is read.
        directory(self.root)
        lock=self.root/'profile.lock'
        fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        self.lock=os.fdopen(fd,'r+')
        try:
            regular(lock)
            try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ProfileError('profile_in_use') from None
            marker=self.root/'environment.json'
            self.profile=self.root/'chromium-profile'
            self.home=self.root/'desktop-home'
            if marker.exists() or marker.is_symlink():
                regular(marker)
                try:record=json.loads(marker.read_text())
                except ValueError:raise ProfileError('profile_record_invalid') from None
                if record!={'schema':1,'owner':owner}:raise ProfileError('profile_owner_mismatch')
                self.status='restored'
            else:
                if self.profile.exists() or self.profile.is_symlink():raise ProfileError('profile_unbound')
                consent=self.root/'consent.json'
                if consent.exists() or consent.is_symlink():
                    regular(consent)
                    try:old=json.loads(consent.read_text())
                    except ValueError:raise ProfileError('profile_record_invalid') from None
                    if old!={'owner':owner,'kind':'local-fictional-consent'}:raise ProfileError('profile_owner_mismatch')
                atomic_json(marker,{'schema':1,'owner':owner})
                self.status='created'
            if self.status=='restored' and (not self.profile.exists() or not self.home.exists()):
                raise ProfileError('profile_missing')
            directory(self.profile);directory(self.home)
            self.recovered_lock=False
        except BaseException:
            self.close();raise

    def before_open(self, browser_running):
        self.validate()
        if browser_running:raise ProfileError('profile_in_use')
        # Remove only Chromium's known stale link names, never their targets.
        # Holding profile.lock excludes a second worker throughout this operation.
        for name in ('SingletonLock','SingletonSocket','SingletonCookie'):
            path=self.profile/name
            if path.is_symlink():
                path.unlink();self.recovered_lock=True
            elif path.exists():raise ProfileError('profile_lock_invalid')

    def validate(self):
        self.network_check()
        marker=self.root/'environment.json';regular(marker)
        try:record=json.loads(marker.read_text())
        except ValueError:raise ProfileError('profile_record_invalid') from None
        if record!={'schema':1,'owner':self.owner}:raise ProfileError('profile_owner_mismatch')
        if not self.profile.exists() or not self.home.exists():raise ProfileError('profile_missing')
        directory(self.profile);directory(self.home)

    def close(self):
        if self.lock is not None:
            self.lock.close();self.lock=None

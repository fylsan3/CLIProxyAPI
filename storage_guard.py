"""Fail-closed storage checks for the isolated local test controller.

These checks do not isolate data from the OS user or Docker administrator.
"""
import os
import socket
import stat
from pathlib import Path


def private_directory(path):
    path = Path(path)
    path.mkdir(mode=0o700, exist_ok=True)
    info = path.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise ValueError('state_directory_unsafe')


def private_file(path, create=False):
    path = Path(path)
    if create:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600) if not path.exists() and not path.is_symlink() else None
        if fd is not None:
            os.close(fd)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) & 0o077):
        raise ValueError('state_file_unsafe')


def control_directory(path, group=None):
    if group is None:
        private_directory(path)
        return
    info = Path(path).lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or info.st_gid != group or stat.S_IMODE(info.st_mode) != 0o750):
        raise ValueError('control_directory_unsafe')


def socket_permissions(path, group=None):
    if group is not None:
        os.chown(path, -1, group)
        os.chmod(path, 0o660)


def prepare_socket(path, group=None):
    path = Path(path)
    control_directory(path.parent, group)
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
        raise ValueError('control_socket_unsafe')
    with socket.socket(socket.AF_UNIX) as probe:
        probe.settimeout(0.5)
        try:
            probe.connect(str(path))
        except ConnectionRefusedError:
            pass
        else:
            raise ValueError('control_socket_in_use')
    path.unlink()


def volume_matches(info, name, scope):
    return bool(isinstance(info, dict) and info.get('Name') == name
                and info.get('Driver') == 'local' and info.get('Scope') == 'local'
                and not info.get('Options')
                and (info.get('Labels') or {}).get('cpa.project.scope') == scope)

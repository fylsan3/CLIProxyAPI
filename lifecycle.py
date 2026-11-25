"""Local ownership and request cleanup; no provider-specific behavior."""
import fcntl
import os
import select
import socket
import stat
import subprocess
import threading


class Lease:
    def __init__(self, path):
        self.fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            info = os.fstat(self.fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_nlink != 1 or info.st_mode & 0o077:
                raise ValueError('control_lock_unsafe')
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(self.fd)
            raise

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


def finish_process(process):
    # Closing stdin cancels the in-container HTTP call before killing the local CLI.
    try:
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
    except OSError:
        pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


class RequestWatch:
    def __init__(self, connection, process, stopping):
        self.done = threading.Event()
        self.cancelled = threading.Event()
        self.reason = None
        self.connection, self.process, self.stopping = connection, process, stopping
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        while not self.done.wait(.05):
            reason = 'controller_stopping' if self.stopping.is_set() else None
            if reason is None and self.connection is not None:
                try:
                    ready, _, _ = select.select([self.connection], [], [], 0)
                    if ready and not self.connection.recv(1, socket.MSG_PEEK | socket.MSG_DONTWAIT):
                        reason = 'client_disconnected'
                except (OSError, ValueError):
                    reason = 'client_disconnected'
            if reason:
                self.reason = reason
                self.cancelled.set()
                finish_process(self.process)
                return

    def close(self):
        self.done.set()
        self.thread.join(5)

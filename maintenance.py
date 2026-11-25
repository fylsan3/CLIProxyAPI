"""Coordinate model admission and explicit container maintenance per account."""
import contextlib,threading

class MaintenanceGate:
    def __init__(self):
        self.lock=threading.RLock();self.active={};self.blocked=set()
    @contextlib.contextmanager
    def request(self,owner):
        with self.lock:
            if owner in self.blocked:raise ValueError('account_maintenance')
            self.active[owner]=self.active.get(owner,0)+1
        try:yield
        finally:
            with self.lock:
                self.active[owner]-=1
                if not self.active[owner]:del self.active[owner]
    @contextlib.contextmanager
    def maintenance(self,owner):
        with self.lock:
            if owner in self.blocked:raise ValueError('account_maintenance')
            if self.active.get(owner):raise ValueError('account_busy')
            self.blocked.add(owner)
        try:yield
        finally:
            with self.lock:self.blocked.discard(owner)
    def status(self,owner):
        with self.lock:return {'maintenance':owner in self.blocked,'admitted_requests':self.active.get(owner,0)}

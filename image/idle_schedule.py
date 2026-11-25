"""A fixed five-minute idle check; no token refresh or cooldown decisions live here."""
import time


class IdleSchedule:
    interval=300

    def __init__(self, now=time.monotonic):
        self.now=now
        self.due_at=0
        self.running=False

    def begin_if_idle(self, active):
        if self.running or active or self.now()<self.due_at:
            return False
        self.running=True
        return True

    def complete(self):
        self.running=False
        self.due_at=self.now()+self.interval

    def remaining(self):
        return max(0,self.due_at-self.now())

"""Observe cgroup memory kills, including cases with no Chromium dump/stderr."""
from pathlib import Path
import threading
import time


def memory_snapshot(root=Path('/sys/fs/cgroup')):
    def number(name):
        try:
            raw=(root/name).read_text().strip()
            return int(raw) if raw.isdigit() else None
        except OSError:return None
    try:events={k:int(v) for k,v in (line.split() for line in (root/'memory.events').read_text().splitlines())}
    except (OSError,ValueError):events={}
    return {'current_bytes':number('memory.current'),'limit_bytes':number('memory.max'),
            'peak_bytes':number('memory.peak'),'oom_kills':events.get('oom_kill',0),
            'oom_events':events.get('oom',0),'observed_at':int(time.time())}


class MemoryObserver:
    def __init__(self,save,root=Path('/sys/fs/cgroup')):
        self.save,self.root=save,root
        self.last=memory_snapshot(root)['oom_kills'];self.stopped=threading.Event()
        self.thread=threading.Thread(target=self.run,daemon=True)

    def poll(self):
        state=memory_snapshot(self.root)
        if state['oom_kills']>self.last:
            delta=state['oom_kills']-self.last;self.last=state['oom_kills']
            self.save({'observed_at':state['observed_at'],'codes':['container_memory_oom_kill'],
                       'new_oom_kills':delta,'memory':state,
                       'attribution':'container; killed process not identified by cgroup counters'})
        return state

    def run(self):
        while not self.stopped.wait(.5):
            try:self.poll()
            except (OSError,ValueError):pass

    def start(self):self.thread.start()
    def close(self):self.stopped.set()

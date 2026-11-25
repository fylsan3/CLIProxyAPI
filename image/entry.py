"""Supervise the offline account's children and report unexpected exits as failure."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from retention import retained, RetentionError
from retention_cli import expected_binding, verify_backups, reconcile_checkpoint, network_copy


def stop_children(processes):
    for process in reversed(processes):
        try:os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:pass
    deadline=time.monotonic()+2
    for process in reversed(processes):
        try:process.wait(max(.01,deadline-time.monotonic()))
        except subprocess.TimeoutExpired:pass
    for process in reversed(processes):
        try:os.killpg(process.pid,signal.SIGKILL)
        except ProcessLookupError:pass
        process.wait()


def run():
    processes=[];stopping=False
    def requested(*unused):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,requested);signal.signal(signal.SIGINT,requested)
    os.umask(0o077)
    def start(argv):
        p=subprocess.Popen(argv,start_new_session=True);processes.append(p);return p
    try:
        start(['/opt/native/worker','serve'])
        start(['python3','-B','/opt/sample/worker.py','serve'])
        while not stopping:
            if any(p.poll() is not None for p in processes):return 1
            time.sleep(.1)
        return 0
    finally:stop_children(processes)


if __name__=='__main__':
    adapter=None
    try:
        adapter=subprocess.Popen(['python3','-B','/opt/native/socks_adapter.py'])
        from network_gate import check
        while True:
            if adapter.poll() is not None:raise ValueError('proxy_monitor_stopped')
            try:check();break
            except (OSError,ValueError,KeyError):time.sleep(.1)
        Path('/run/network/lifecycle.json').write_text('{"network_passed":true,"account_state_opened":true}')
        with retained('/state',expected_binding()) as store:
            store.validate()
            network_copy(store.root)
            verify_backups(store)
            reconcile_checkpoint(store)
            os.environ['CPA_CREDENTIAL_BACKUP']='/backup/credentials/latest.json'
            sys.exit(run())
    except (RetentionError,OSError,ValueError,KeyError):
        print('environment_or_network_protection_failed',flush=True)
        sys.exit(1)
    finally:
        if adapter is not None:
            adapter.terminate();adapter.wait(5)

"""Run the existing image's network probe and report safe stage/error frames."""
import json
import subprocess
import tempfile
import threading
from creation_progress import CreationFailure

# Same pinned locale probe, firewall and SOCKS transport. Only progress/error reporting is added.
PROBE_SCRIPT = r'''
import json,sys
sys.path.insert(0,'/opt/native')
from locale_probe import probe
try:
    probe(json.load(sys.stdin))
except Exception:
    print(json.dumps({'error':'exit_timezone_unavailable'}),flush=True);sys.exit(1)
'''


def discover(command, config, report, timeout=30):
    with tempfile.TemporaryFile() as errors:
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errors,text=True)
        expired=threading.Event()
        def terminate():
            expired.set()
            process.kill()
        timer=threading.Timer(timeout,terminate);timer.daemon=True;timer.start()
        result=None;error=None
        try:
            process.stdin.write(json.dumps(config));process.stdin.close()
            while True:
                line=process.stdout.readline(16385)
                if not line:break
                if len(line)>16384:raise CreationFailure('probe_runtime_failed')
                try:frame=json.loads(line)
                except ValueError:raise CreationFailure('probe_runtime_failed') from None
                if not isinstance(frame,dict):raise CreationFailure('probe_runtime_failed')
                if frame.get('step')=='checking_exit':report('checking_exit')
                if 'location' in frame:result=frame['location']
                if 'error' in frame:error=CreationFailure(frame['error'])
            code=process.wait()
            if expired.is_set():raise CreationFailure('proxy_check_timeout')
            if error:raise error
            if code or not isinstance(result,dict):raise CreationFailure('probe_runtime_failed')
            return result
        finally:
            timer.cancel()
            if process.poll() is None:process.kill()
            process.wait();process.stdout.close()
            if not process.stdin.closed:process.stdin.close()

"""Run the existing image's network probe and report safe stage/error frames."""
import json
import subprocess
import tempfile
import threading
from creation_progress import CreationFailure

# Same pinned locale probe, firewall and SOCKS transport. Only progress/error reporting is added.
PROBE_SCRIPT = r'''
import json,sys,ssl,subprocess
sys.path.insert(0,'/opt/native')
import locale_probe

def emit(value): print(json.dumps(value),flush=True)
class ReportingAdapter(locale_probe.Adapter):
    def connect(self,*args,**kwargs):
        connection=super().connect(*args,**kwargs)
        emit({'step':'checking_exit'})
        return connection
locale_probe.Adapter=ReportingAdapter
try:
    result=locale_probe.probe(json.load(sys.stdin))
    emit({'location':result})
except Exception as error:
    known={'proxy_auth_method_rejected','proxy_auth_rejected','proxy_connect_rejected'}
    code=str(error) if isinstance(error,ValueError) and str(error) in known else 'exit_timezone_unavailable'
    if isinstance(error,subprocess.CalledProcessError):code='network_guard_setup_failed'
    elif isinstance(error,ssl.SSLError):code='exit_tls_failed'
    elif isinstance(error,TimeoutError):code='proxy_check_timeout'
    elif isinstance(error,(ConnectionError,OSError)):code='proxy_connection_failed'
    emit({'error':code});sys.exit(1)
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

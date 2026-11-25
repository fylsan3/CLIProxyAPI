"""Shared local test process and Docker helpers; never accesses real accounts."""
import concurrent.futures,contextlib,hashlib,http.client,json,os,secrets,socket,sqlite3,subprocess,sys,tempfile,time
from pathlib import Path

ROOT=Path(__file__).resolve().parent
from central_policy import mac_profile
from host_runtime import docker_cli
CLI=docker_cli()
def docker(*args):return subprocess.check_output(CLI+list(args),text=True,stderr=subprocess.STDOUT,timeout=30).strip()
def stop(p):
    if p.poll() is None:p.terminate();p.wait(10)
def wait(fn):
    last=None
    for _ in range(120):
        try:
            last=fn()
            if last:return last
        except (OSError,ConnectionError):pass
        time.sleep(.15)
    raise RuntimeError('native worker not ready: '+str(last))

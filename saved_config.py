"""Initialize once; existing CPA YAML is read by the native parser, never rewritten."""
import json,os,secrets,socket,subprocess,sys
from pathlib import Path
from storage_guard import private_file

def create_private(path, data):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())

def prepare(root,state,requested_port=0,refresh_workers=None,max_request_body_bytes=None):
    cfgpath=state/'config.yaml';keypath=state/'client-key'
    for path in (cfgpath,keypath):private_file(path)
    if cfgpath.exists() and not keypath.exists():raise ValueError('saved_management_key_missing_no_reset')
    if not keypath.exists():create_private(keypath,secrets.token_hex(24).encode())
    key=keypath.read_text().strip()
    if len(key)!=48 or any(c not in '0123456789abcdef' for c in key):raise ValueError('invalid_test_client_key')
    if not cfgpath.exists():
        with socket.socket() as listener:listener.bind(('127.0.0.1',requested_port));port=listener.getsockname()[1]
        cfg={'host':'127.0.0.1','port':port,'auth-dir':str(state/'auth-empty'),'api-keys':[key],
             'remote-management':{'secret-key':key,'disable-control-panel':False},'request-log':False,
             'oauth':{'auth-dir':str(state/'auth-empty')},
             'routing':{'strategy':'fill-first','retry':{'request-retry':0,'max-retry-interval':0}}}
        if max_request_body_bytes is not None:
            cfg['max-request-body-bytes']=max_request_body_bytes
        if refresh_workers is not None:
            if refresh_workers<1:raise ValueError('refresh_workers_must_be_positive')
            cfg['oauth']['auth-auto-refresh-workers']=refresh_workers
        create_private(cfgpath,json.dumps(cfg).encode())
    result=subprocess.run([str(root/'config'/('inspect-'+sys.platform)),str(cfgpath),str(state)],
                          input=key,text=True,capture_output=True)
    if result.returncode:raise ValueError('saved_configuration_invalid_no_overwrite')
    actual=json.loads(result.stdout)
    if requested_port and requested_port!=actual['port']:raise ValueError('saved_port_conflict_no_overwrite')
    if refresh_workers is not None and refresh_workers!=actual['refresh_workers']:raise ValueError('saved_refresh_workers_conflict_no_overwrite')
    if max_request_body_bytes is not None and max_request_body_bytes!=actual['max_request_body_bytes']:raise ValueError('saved_body_limit_conflict_no_overwrite')
    return cfgpath,keypath,key,actual['port']

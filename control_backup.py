"""Authenticated offline control backups. Never starts containers or replays work."""
import argparse,base64,contextlib,hashlib,json,os,secrets,shutil,sqlite3,stat,subprocess,sys,tempfile
from pathlib import Path,PurePosixPath
from lifecycle import Lease
ROOT=Path(__file__).resolve().parent
LIMIT=64*1024*1024
MAGIC=b'CPA-CONTROL-1\n'
FIXED={'config.yaml','client-key','broker-private/accounts.json','broker-private/control.sqlite','broker-private/package.key','broker-private/network-fixture.json','broker-private/backup-destination.json'}

def allowed(name):
 p=PurePosixPath(name)
 if p.is_absolute() or '..' in p.parts or str(p)!=name:return False
 if name in FIXED:return True
 if p.parent==PurePosixPath('broker-private/environments') and p.suffix=='.json':return True
 return p.parent==PurePosixPath('broker-private') and p.suffix=='.json' and p.name.startswith(('credential-floor-','package-status-'))

def private(path,directory=False):
 info=path.lstat()
 if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)) or info.st_uid!=os.getuid() or info.st_mode&0o077 or (not directory and info.st_nlink!=1):raise ValueError('unsafe_control_storage')

def check_path(path,directory=False):
 # Do not follow a symlink in any parent, including a disappeared control root.
 path=Path(os.path.abspath(path))
 for parent in reversed([path,*path.parents]):
  if parent.is_symlink():raise ValueError('symlink_path_rejected')
 if path.exists():private(path,directory)
 return path

def create(path,data):
 path=check_path(path);private(path.parent,True)
 fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
 with os.fdopen(fd,'wb') as out:out.write(data);out.flush();os.fsync(out.fileno())

def startup_lease(state):
    state=check_path(state,True)
    state.parent.mkdir(parents=True,mode=0o700,exist_ok=True)
    gate=Lease(state.parent/('.'+state.name+'.restore.lock'))
    try:
        state.mkdir(mode=0o700,exist_ok=True);private(state,True)
        return Lease(state/'launch.lock')
    finally:gate.close()

def cli():
 from host_runtime import docker_cli
 return docker_cli()

CRYPTO=r'''
import base64,json,os,sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
meta=json.loads(sys.stdin.buffer.readline());key=base64.b64decode(meta['key'],validate=True);raw=sys.stdin.buffer.read(67108865)
if len(raw)>67108864 or len(key)!=32:raise ValueError('input_invalid')
magic=b'CPA-CONTROL-1\n'
if meta['operation']=='seal':
 nonce=os.urandom(12);out=magic+nonce+AESGCM(key).encrypt(nonce,raw,magic)
else:
 if not raw.startswith(magic):raise ValueError('format_invalid')
 offset=len(magic);out=AESGCM(key).decrypt(raw[offset:offset+12],raw[offset+12:],magic)
sys.stdout.buffer.write(out)
'''
def crypt(operation,data,key):
 if len(data)>LIMIT:raise ValueError('control_backup_too_large')
 image=json.loads((ROOT/'image.json').read_text())['id']
 cmd=cli()+['run','--rm','-i','--pull=never','--network','none','--read-only','--user','1001:1001','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','512m','--pids-limit','40','--entrypoint','python3',image,'-B','-c',CRYPTO]
 payload=json.dumps({'operation':operation,'key':base64.b64encode(key).decode()}).encode()+b'\n'+data
 p=subprocess.run(cmd,input=payload,capture_output=True,timeout=60)
 if p.returncode:raise ValueError('control_backup_authentication_or_crypto_failed')
 return p.stdout

def key_from(path):
 path=check_path(path);private(path);key=path.read_bytes()
 if len(key)!=32:raise ValueError('recovery_key_invalid')
 return key

def collect(state):
 state=check_path(state,True);private(state,True);private(state/'broker-private',True)
 if any((state/'broker-private').glob('restore-*.json')):raise ValueError('account_restore_in_progress')
 entries={};total=0
 for path in sorted(state.rglob('*')):
  name=path.relative_to(state).as_posix()
  if not allowed(name):continue
  check_path(path);private(path)
  if name=='broker-private/control.sqlite':
   with tempfile.TemporaryDirectory(prefix='cpa-control-db-') as tmp:
    copy=Path(tmp)/'snapshot.sqlite'
    with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as src,sqlite3.connect(copy) as dst:
     src.backup(dst)
     if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('control_database_invalid')
    raw=copy.read_bytes()
  else:raw=path.read_bytes()
  total+=len(raw)
  if total>LIMIT//2:raise ValueError('control_snapshot_too_large')
  entries[name]={'data':base64.b64encode(raw).decode(),'sha256':hashlib.sha256(raw).hexdigest()}
 missing=FIXED-set(entries)
 if missing:raise ValueError('control_snapshot_incomplete')
 if any(json.loads(base64.b64decode(x['data'])).get('phase') in ('authorizing','exchanging_credentials','saving_backup','restoring') for name,x in entries.items() if name.startswith('broker-private/environments/protection-')):raise ValueError('account_operation_in_progress')
 return {'schema':1,'source_state':str(state),'candidate':'control-recovery1','files':entries}

def export(state,output,keypath):
 state=check_path(state,True);output=check_path(output);keypath=check_path(keypath)
 if output.exists():raise ValueError('backup_exists_no_overwrite')
 if keypath.is_relative_to(state) or output.is_relative_to(state):raise ValueError('recovery_files_must_be_outside_state')
 private(output.parent,True);private(keypath.parent,True)
 with contextlib.ExitStack() as stack:
  for path in [state/'launch.lock',state/'broker-private/control.lock']:
   lease=Lease(path);stack.callback(lease.close)
  snapshot=collect(state)
  if not keypath.exists():create(keypath,secrets.token_bytes(32))
  key=key_from(keypath);raw=json.dumps(snapshot,separators=(',',':')).encode();encrypted=crypt('seal',raw,key)
  if crypt('open',encrypted,key)!=raw:raise ValueError('control_backup_verify_failed')
  create(output,encrypted)
 return {'verified':True,'files':len(snapshot['files']),'bytes':len(encrypted),'sha256':hashlib.sha256(encrypted).hexdigest(),'starts_accounts':False}

def decode(bundle,keypath,state):
 bundle=check_path(bundle);private(bundle)
 if bundle.stat().st_size>LIMIT:raise ValueError('control_backup_too_large')
 value=json.loads(crypt('open',bundle.read_bytes(),key_from(keypath)))
 if value.get('schema')!=1 or value.get('source_state')!=str(state):raise ValueError('restore_path_mismatch')
 files=value.get('files');decoded={};total=0
 if not isinstance(files,dict) or not FIXED.issubset(files) or len(files)>10000:raise ValueError('control_manifest_invalid')
 for name,item in files.items():
  if not allowed(name):raise ValueError('control_entry_not_allowed')
  data=base64.b64decode(item['data'],validate=True);total+=len(data)
  if total>LIMIT//2 or hashlib.sha256(data).hexdigest()!=item['sha256']:raise ValueError('control_entry_invalid')
  decoded[name]=data
 return decoded

def restore(bundle,keypath,state):
 state=check_path(state,True);private(state.parent,True)
 # A fresh destination only: never overwrite a live controller or stale credentials.
 if state.exists():raise ValueError('restore_destination_exists')
 lease=Lease(state.parent/('.'+state.name+'.restore.lock'))
 try:
  files=decode(bundle,keypath,state)
  if shutil.disk_usage(state.parent).free<sum(map(len,files.values()))+64*1024*1024:raise ValueError('insufficient_restore_space')
  tmp=Path(tempfile.mkdtemp(prefix='.'+state.name+'-restore-',dir=state.parent))
  try:
   for name,data in files.items():
    path=tmp/name;path.parent.mkdir(parents=True,mode=0o700,exist_ok=True);create(path,data)
   with sqlite3.connect('file:'+str(tmp/'broker-private/control.sqlite')+'?mode=ro',uri=True) as db:
    if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('restored_database_invalid')
   # No Docker, network, credential loading, or account startup occurs after decrypting.
   if state.exists():raise ValueError('restore_destination_exists')
   tmp.rename(state)
   fd=os.open(state.parent,os.O_RDONLY)
   try:os.fsync(fd)
   finally:os.close(fd)
  finally:
   if tmp.exists():shutil.rmtree(tmp)
 finally:lease.close()
 return {'restored':True,'files':len(files),'starts_accounts':False,'same_path_only':True}

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('operation',choices=['export','restore']);p.add_argument('--state',type=Path,required=True);p.add_argument('--bundle',type=Path,required=True);p.add_argument('--key-file',type=Path,required=True);a=p.parse_args()
 try:print(json.dumps(export(a.state,a.bundle,a.key_file) if a.operation=='export' else restore(a.bundle,a.key_file,a.state)))
 except Exception as e:print(type(e).__name__+': '+str(e),file=sys.stderr);raise SystemExit(1)

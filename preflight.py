"""Read-only startup capacity checks; never prunes images or account volumes."""
import argparse,json,os,shutil,subprocess,sys
from pathlib import Path
from control_backup import cli
ROOT=Path(__file__).resolve().parent
MIN_HOST=256*1024*1024
MIN_ENGINE=512*1024*1024

def existing_parent(path):
 path=Path(os.path.abspath(path))
 while not path.exists():
  if path.is_symlink():raise ValueError('capacity_path_symlink')
  path=path.parent
 if path.is_symlink() or not path.is_dir():raise ValueError('capacity_path_invalid')
 return path

def evaluate(host,backup,engine):
 issues=[]
 if host<MIN_HOST:issues.append('control_disk_low')
 if backup<MIN_HOST:issues.append('backup_disk_low')
 if engine<MIN_ENGINE:issues.append('container_disk_low')
 return {'ready':not issues,'issues':issues,'host_free_bytes':host,'backup_free_bytes':backup,'container_free_bytes':engine,'minimum_host_bytes':MIN_HOST,'minimum_container_bytes':MIN_ENGINE,'capacity_for_account_count_verified':False}

def check(state,backup=None):
 image=json.loads((ROOT/'image.json').read_text())['id']
 host=shutil.disk_usage(existing_parent(state)).free
 destination=backup
 saved=Path(state)/'broker-private/backup-destination.json'
 if destination is None and saved.is_file():destination=json.loads(saved.read_text())['path']
 backup_free=shutil.disk_usage(existing_parent(destination or state)).free
 script="import json,os;v=os.statvfs('/');print(json.dumps({'available':v.f_bavail*v.f_frsize}))"
 cmd=cli()+['run','--rm','--pull=never','--network','none','--read-only','--user','1001:1001','--cap-drop','ALL','--security-opt','no-new-privileges','--memory','128m','--pids-limit','20','--entrypoint','python3',image,'-B','-c',script]
 p=subprocess.run(cmd,capture_output=True,text=True,timeout=20)
 if p.returncode:raise ValueError('container_capacity_probe_failed')
 return evaluate(host,backup_free,int(json.loads(p.stdout)['available']))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--state',type=Path,required=True);p.add_argument('--backup-directory',type=Path);a=p.parse_args()
 try:
  result=check(a.state,a.backup_directory);print(json.dumps(result,indent=2));raise SystemExit(0 if result['ready'] else 2)
 except (OSError,ValueError,subprocess.SubprocessError) as e:print(json.dumps({'ready':False,'error':str(e)}));raise SystemExit(2)

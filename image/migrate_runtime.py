"""Offline clone migration. Only runtime bindings change; original volumes are read-only."""
import hashlib,json,os,shutil,sys
from pathlib import Path
sys.path.insert(0,'/opt/native')
from retention import read_json,write_json,digest,binding
from bundle_io import SnapshotReader
spec=json.load(sys.stdin);old=spec['old'];new=spec['new']
expected=binding(old['owner'],old['environment_id'],old['runtime']);updated=binding(new['owner'],new['environment_id'],new['runtime'])
assert {k:v for k,v in old['runtime'].items() if k!='worker_sha256'}=={k:v for k,v in new['runtime'].items() if k!='worker_sha256'},'environment_change_rejected'
assert read_json(Path('/old-state/retention.json'))==expected
for p in Path('/old-backup').glob('*/manifest.json'):SnapshotReader(expected).verify_snapshot(p.parent)
def copy(source,target):
 assert not any(target.iterdir()),'nonempty_destination'
 shutil.copytree(source,target,dirs_exist_ok=True,symlinks=True)
for src,dst in [('/old-state','/state'),('/old-backup','/backup')]:copy(Path(src),Path(dst))
credential=digest(Path('/state/native-auth.json'))
write_json(Path('/state/retention.json'),updated)
write_json(Path('/backup/credentials/binding.json'),updated)
for path in Path('/backup').glob('*/manifest.json'):
 manifest=read_json(path);assert manifest['binding']==expected
 record=path.parent/'data/retention.json';write_json(record,updated)
 manifest['binding']=updated;manifest['files']['retention.json'].update(sha256=digest(record),bytes=record.stat().st_size)
 write_json(path,manifest);SnapshotReader(updated).verify_snapshot(path.parent)
def hashes(root):
 return {str(p.relative_to(root)):digest(p) for p in root.rglob('*') if p.is_file() and not p.is_symlink() and p.name not in ('.retention.lock','profile.lock') and str(p.relative_to(root))!='retention.json'}
assert hashes(Path('/old-state'))==hashes(Path('/state')),'account_content_changed'
assert digest(Path('/state/native-auth.json'))==credential
print(json.dumps({'credential_sha256':credential,'account_files_unchanged':True,'manifest_sha256':digest(Path('/backup')/spec['snapshot']/'manifest.json')}))

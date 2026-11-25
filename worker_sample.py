"""Explicit one-input arming/export; never authorizes, refreshes or restarts an account."""
import argparse,gzip,hashlib,json,os,re,secrets,subprocess,tarfile,tempfile,time
from pathlib import Path
from host_runtime import docker_cli
from request_sample import private_dir,write_private
CLI=docker_cli()
def input_hash(raw):
    if raw.startswith(b'\x1f\x8b'):raw=gzip.decompress(raw)
    return hashlib.sha256(json.dumps(json.loads(raw)).encode()).hexdigest()
def arm(container,raw):
    ident=secrets.token_hex(12);data={'id':ident,'input_sha256':input_hash(raw),'expires':int(time.time())+2700}
    script="import os,sys,json;from pathlib import Path;d=json.load(sys.stdin);assert Path('/opt/native/worker').is_file();p=Path('/state/model-sample-arm.json');fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600);f=os.fdopen(fd,'w');json.dump(d,f);f.flush();os.fsync(f.fileno());f.close()"
    subprocess.run(CLI+['exec','--user','1001:1001','-i',container,'python3','-c',script],input=json.dumps(data),text=True,check=True,capture_output=True)
    return data

def collect(container,ident,directory):
    if not re.fullmatch('[0-9a-f]{24}',ident):raise ValueError('invalid_sample_id')
    target=Path(directory)
    if target.exists():raise ValueError('new_output_directory_required')
    private_dir(target)
    script="import io,sys,tarfile;from pathlib import Path;p=Path('/state/model-samples')/sys.argv[1];assert p.is_dir() and not p.is_symlink();t=tarfile.open(fileobj=sys.stdout.buffer,mode='w|');[(t.add(x,arcname=str(x.relative_to(p)),recursive=False)) for x in sorted(p.rglob('*')) if x.is_file() and not x.is_symlink() and x.suffix in ('.json','.bin')];t.close()"
    with tempfile.TemporaryFile() as tmp:
        subprocess.run(CLI+['exec','--user','1001:1001',container,'python3','-c',script,ident],stdout=tmp,check=True,stderr=subprocess.PIPE)
        tmp.seek(0)
        with tarfile.open(fileobj=tmp,mode='r:') as archive:
            for item in archive:
                rel=Path(item.name)
                if not item.isfile() or rel.is_absolute() or '..' in rel.parts:raise ValueError('unsafe_sample_path')
                out=target/rel;private_dir(out.parent);write_private(out,archive.extractfile(item).read())
    records=list(target.glob('*/response.json'))
    if not records:raise ValueError('sample_not_yet_sent')
    for path in records:
        for kind in ('request','response'):
            meta=json.loads((path.parent/(kind+'.json')).read_text());body=path.parent/(kind+'.bin')
            if meta.get('sha256') and (not body.exists() or hashlib.sha256(body.read_bytes()).hexdigest()!=meta['sha256']):raise ValueError('sample_hash_mismatch')
    return {'sample_id':ident,'exchanges':len(records),'complete_responses':sum(json.loads(p.read_text()).get('complete') is True for p in records)}
if __name__=='__main__':
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('arm');p.add_argument('--container',required=True);p.add_argument('--body-file',type=Path,required=True)
    p=sub.add_parser('collect');p.add_argument('--container',required=True);p.add_argument('--sample-id',required=True);p.add_argument('--directory',type=Path,required=True)
    args=parser.parse_args()
    result=arm(args.container,args.body_file.read_bytes()) if args.action=='arm' else collect(args.container,args.sample_id,args.directory)
    print(json.dumps(result))

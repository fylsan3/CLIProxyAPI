"""Authenticated, bounded archive transport for committed offline account backups."""
import base64,gzip,hashlib,io,json,os,re,shutil,stat,sys,tarfile,tempfile
from pathlib import Path,PurePosixPath
from cryptography.hazmat.primitives.ciphers import Cipher,algorithms,modes
from retention import Store,binding,digest,private,read_json,write_json

MAGIC=b'CPA-BACKUP-1\n'
LIMIT=128*1024*1024
EXPANDED_LIMIT=512*1024*1024

class SnapshotReader(Store):
    # Only verify_snapshot is used; no running account disk is opened or locked.
    def __init__(self,expected):self.expected=expected

def context(spec):
    card=spec['card'];expected=binding(card['owner'],card['environment_id'],card['runtime'])
    snapshot=spec['snapshot']
    if not re.fullmatch('[a-z0-9-]{1,100}',snapshot):raise ValueError('snapshot_invalid')
    return card,expected,snapshot

def check(root,spec):
    card,expected,snapshot=context(spec);reader=SnapshotReader(expected)
    reader.verify_snapshot(root/'initial');reader.verify_snapshot(root/snapshot)
    if read_json(root/'credentials/binding.json')!=expected:raise ValueError('credential_binding_mismatch')
    checkpoint=read_json(root/'credentials/latest.json')
    if checkpoint['environment_id']!=card['environment_id'] or checkpoint['record']['owner']!=card['owner']:raise ValueError('checkpoint_mismatch')
    network=(root/snapshot/'data/network-config.json').read_bytes()
    if hashlib.sha256(network).hexdigest()!=card['network_config_sha256']:raise ValueError('network_config_mismatch')
    return checkpoint['record']['revision']

def key(spec):
    value=base64.b64decode(spec.pop('key'),validate=True)
    if len(value)!=32:raise ValueError('backup_key_invalid')
    return value

def export(spec,secret,out):
    root=Path('/backup');card,expected,snapshot=context(spec)
    revision=check(root,spec)
    checkpoint=(root/'credentials/latest.json').read_bytes()
    revision=json.loads(checkpoint)['record']['revision']
    metadata=dict(card=card,snapshot=snapshot,revision=revision,schema=1)
    nonce=os.urandom(12);header=MAGIC+nonce
    encryptor=Cipher(algorithms.AES(secret),modes.GCM(nonce)).encryptor();encryptor.authenticate_additional_data(header)
    out.write(header)
    class Writer:
        size=0
        def write(self,data):
            self.size+=len(data)
            if self.size>LIMIT:raise ValueError('backup_too_large')
            out.write(encryptor.update(data));return len(data)
    with gzip.GzipFile(fileobj=Writer(),mode='wb',compresslevel=3,mtime=0) as compressed, tarfile.open(fileobj=compressed,mode='w|',format=tarfile.PAX_FORMAT) as archive:
        def add(name,data,mode=0o600):
            entry=tarfile.TarInfo(name);entry.size=len(data);entry.mode=mode
            archive.addfile(entry,io.BytesIO(data))
        add('metadata.json',json.dumps(metadata,sort_keys=True).encode())
        expanded=0
        for name in ('initial',snapshot,'credentials'):
            for path in sorted((root/name).rglob('*')):
                info=path.lstat();relative='backup/'+path.relative_to(root).as_posix()
                if stat.S_ISDIR(info.st_mode):
                    entry=tarfile.TarInfo(relative);entry.type=tarfile.DIRTYPE;entry.mode=0o700;archive.addfile(entry);continue
                expanded+=info.st_size
                if expanded>EXPANDED_LIMIT:raise ValueError('backup_expanded_too_large')
                private(path)
                if not stat.S_ISREG(info.st_mode):raise ValueError('unsafe_backup_entry')
                if path==root/'credentials/latest.json':add(relative,checkpoint);continue
                entry=tarfile.TarInfo(relative);entry.size=info.st_size;entry.mode=0o700 if info.st_mode&0o100 else 0o600
                with path.open('rb') as source:archive.addfile(entry,source)
    if checkpoint!=(root/'credentials/latest.json').read_bytes():raise ValueError('checkpoint_changed_retry_export')
    out.write(encryptor.finalize());out.write(encryptor.tag);out.flush()
    return {'revision':revision,'snapshot':snapshot}

def restore(spec,secret,source):
    card,expected,snapshot=context(spec)
    header=source.read(len(MAGIC)+12)
    if len(header)!=len(MAGIC)+12 or not header.startswith(MAGIC):raise ValueError('backup_format_invalid')
    decryptor=Cipher(algorithms.AES(secret),modes.GCM(header[-12:])).decryptor();decryptor.authenticate_additional_data(header)
    with tempfile.TemporaryDirectory(prefix='verified-bundle-') as temp:
        temp=Path(temp);archive_path=temp/'archive.tar';total=0;tail=b''
        with archive_path.open('wb') as output:
            while True:
                block=source.read(1024*1024)
                if not block:break
                total+=len(block)
                if total>LIMIT+16:raise ValueError('backup_too_large')
                buffer=tail+block
                if len(buffer)>16:output.write(decryptor.update(buffer[:-16]));tail=buffer[-16:]
                else:tail=buffer
            if len(tail)!=16:raise ValueError('backup_truncated')
            output.write(decryptor.finalize_with_tag(tail))
        extracted=temp/'verified';extracted.mkdir(mode=0o700);names=set()
        expanded=0
        with tarfile.open(archive_path,'r:*') as archive:
            for entry in archive:
                expanded+=entry.size
                if expanded>EXPANDED_LIMIT:raise ValueError('backup_expanded_too_large')
                rel=PurePosixPath(entry.name)
                if not (entry.isfile() or entry.isdir()) or rel.is_absolute() or '..' in rel.parts or str(rel)!=entry.name or entry.name in names:raise ValueError('unsafe_archive_entry')
                if entry.name!='metadata.json' and not (len(rel.parts)>2 and rel.parts[0]=='backup' and rel.parts[1] in ('initial',snapshot,'credentials')):raise ValueError('unexpected_archive_entry')
                names.add(entry.name)
                if len(names)>20000:raise ValueError('too_many_backup_files')
                target=extracted/rel
                if entry.isdir():target.mkdir(mode=0o700,parents=True,exist_ok=True);continue
                target.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
                with archive.extractfile(entry) as inp,target.open('xb') as out:shutil.copyfileobj(inp,out)
                target.chmod(0o700 if entry.mode&0o100 else 0o600)
        metadata=read_json(extracted/'metadata.json')
        if metadata['card']!=card or metadata['snapshot']!=snapshot:raise ValueError('backup_account_mismatch')
        revision=check(extracted/'backup',spec)
        if revision!=metadata['revision'] or revision<spec.get('minimum_revision',0):raise ValueError('stale_credential_backup')
        # Integrity and binding checks finish before writing any destination volume.
        destination=Path('/backup');network=Path('/network-config')
        if any(destination.iterdir()) or any(network.iterdir()):raise ValueError('restore_destination_not_empty')
        shutil.copytree(extracted/'backup',destination,dirs_exist_ok=True)
        config=(destination/snapshot/'data/network-config.json').read_bytes();cfg=json.loads(config)
        (network/'config.json').write_bytes(config);(network/'timezone').write_text(cfg['timezone']+'\n')
        zone=Path('/usr/share/zoneinfo')/cfg['timezone']
        if zone.resolve().is_relative_to(Path('/usr/share/zoneinfo').resolve()) is False:raise ValueError('invalid_timezone')
        (network/'localtime').write_bytes(zone.read_bytes())
        for p in network.iterdir():p.chmod(0o600)
        return {'revision':revision,'manifest_sha256':digest(destination/snapshot/'manifest.json')}

def main():
    os.umask(0o077)
    spec=json.loads(sys.stdin.buffer.readline(32768));secret=key(spec)
    if sys.argv[1]=='export':print(json.dumps(export(spec,secret,sys.stdout.buffer)),file=sys.stderr)
    elif sys.argv[1]=='restore':print(json.dumps(restore(spec,secret,sys.stdin.buffer)))
    else:raise ValueError('unknown_backup_action')

if __name__=='__main__':
    try:main()
    except Exception as error:
        code=str(error) if isinstance(error,ValueError) and str(error) in {'backup_too_large','backup_expanded_too_large','checkpoint_changed_retry_export','backup_format_invalid','backup_truncated'} else 'backup_transfer_failed'
        print(json.dumps({'error':code}),file=sys.stderr);sys.exit(1)

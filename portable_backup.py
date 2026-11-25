"""Account-bound encrypted packages. The central CPA never opens package keys."""
import base64,hashlib,json,os,secrets,subprocess,tempfile,time,uuid,threading,queue
from pathlib import Path
from network_control import DOCKER,docker
from retention import atomic,private,read_json,write_json

def configure_destination(folder,path):
    path=Path(path).absolute();private(path,directory=True)
    config=folder/'backup-destination.json'
    if config.exists():
        saved=read_json(config)
        if saved['path']!=str(path) or read_json(path/'.destination.json')['id']!=saved['id']:raise ValueError('backup_destination_changed_no_overwrite')
        return
    marker=path/'.destination.json'
    if not marker.exists():
        if any(path.iterdir()):raise ValueError('new_backup_destination_not_empty')
        write_json(marker,{'id':str(uuid.uuid4())})
    write_json(config,{'path':str(path),'id':read_json(marker)['id']})

class Packages:
    def __init__(self,broker):
        self.broker=broker;self.folder=broker.folder
        config=self.folder/'backup-destination.json'
        self.destination=Path(read_json(config)['path']) if config.exists() else self.folder/'portable-backups'
        if not config.exists():
            self.destination.mkdir(mode=0o700,exist_ok=False)
            write_json(self.destination/'.destination.json',{'id':str(uuid.uuid4())})
            write_json(config,{'path':str(self.destination),'id':read_json(self.destination/'.destination.json')['id']})
        private(self.destination,directory=True)
        if read_json(self.destination/'.destination.json')['id']!=read_json(config)['id']:raise ValueError('backup_destination_mismatch')
        self.keypath=self.folder/'package.key'
        if not self.keypath.exists():
            if any(self.destination.glob('*/latest.json')):raise ValueError('backup_key_missing_no_reset')
            atomic(self.keypath,secrets.token_bytes(32))
        private(self.keypath)
        if len(self.keypath.read_bytes())!=32:raise ValueError('backup_key_invalid')
        self.jobs=queue.Queue();self.pending=set();self.lock=threading.Lock();self.stopping=threading.Event();self.processes=set();self.metadata_warnings=set();self.observed_revisions={};self.last_automatic={}
        self.thread=threading.Thread(target=self.run,daemon=True);self.thread.start()

    def enqueue(self,owner):
        with self.lock:
            if not self.stopping.is_set() and owner not in self.pending:self.pending.add(owner);self.jobs.put(owner)
    def observe_revision(self,owner,revision):
        with self.lock:
            changed=revision>self.observed_revisions.get(owner,0)
            if changed:self.observed_revisions[owner]=revision
        if changed:self.note_revision(owner,revision)
        status=self.status(owner)
        if status.get('revision',0)>=revision and not status.get('environment_outdated'):return
        if not self.broker.protection.state(owner).get('backup_verified'):return
        now=time.monotonic()
        with self.lock:
            if owner in self.pending or now-self.last_automatic.get(owner,-1000)<300:return
            self.last_automatic[owner]=now
        self.enqueue(owner)
    def note_revision(self,owner,revision):
        # An auxiliary backup observation must not turn a successful CPA refresh into failure.
        with self.lock:
            try:
                path=self.folder/('credential-floor-'+owner+'.json')
                previous=read_json(path)['revision'] if path.exists() else 0
                write_json(path,{'revision':max(previous,revision)})
                self.metadata_warnings.discard(owner)
            except (OSError,ValueError,KeyError):self.metadata_warnings.add(owner)
    def run(self):
        while not self.stopping.is_set():
            owner=self.jobs.get()
            if owner is None:return
            try:
                result=self.export(owner)
                self.note_revision(owner,result['revision'])
                failed=False
            except Exception as error:failed=True;failure_code=str(error) if isinstance(error,ValueError) and str(error) in {'backup_too_large','backup_expanded_too_large','checkpoint_changed_retry_export','backup_export_failed'} else 'backup_export_failed'
            try:write_json(self.folder/('package-status-'+owner+'.json'),{'error':failed,'error_code':failure_code if failed else None,'updated_at':int(time.time())})
            except (OSError,ValueError):
                # A full or detached disk must not kill the queue for other accounts.
                with self.lock:self.metadata_warnings.add(owner)
            finally:
                with self.lock:self.pending.discard(owner)
    def close(self):
        with self.lock:
            self.stopping.set()
            for process in self.processes:
                if process.poll() is None:process.terminate()
        self.jobs.put(None);self.thread.join(5)


    def key(self):
        private(self.keypath)
        value=self.keypath.read_bytes()
        if len(value)!=32:raise ValueError('backup_key_invalid')
        return base64.b64encode(value).decode()
    def target(self,card):
        if str(uuid.UUID(card['environment_id']))!=card['environment_id']:raise ValueError('environment_id_invalid')
        private(self.destination,directory=True)
        config=read_json(self.folder/'backup-destination.json')
        if read_json(self.destination/'.destination.json')['id']!=config['id']:raise ValueError('backup_destination_mismatch')
        target=self.destination/card['environment_id']
        if not target.exists():target.mkdir(mode=0o700)
        private(target,directory=True);return target

    def status(self,owner):
        try:
            path=self.broker.protection.control.card(owner)
            if not path.exists() and not path.is_symlink():
                with self.broker.connect() as db:bound=db.execute('SELECT 1 FROM bindings WHERE owner=?',(owner,)).fetchone()
                if not bound:return {'state':'not_created','off_host_verified':False}
            card=read_json(path);target=self.target(card)
            status=self.folder/('package-status-'+owner+'.json')
            warning=(read_json(status).get('error',False) if status.exists() else False) or owner in self.metadata_warnings
            if not (target/'latest.json').exists():return {'state':'not_exported','warning':warning,'error_code':read_json(status).get('error_code') if status.exists() else None,'off_host_verified':False}
            receipt=read_json(target/'latest.json')
            floor=self.folder/('credential-floor-'+owner+'.json')
            current=read_json(floor)['revision'] if floor.exists() else receipt['revision']
            stale=current>receipt['revision']
            saved=receipt.get('spec',{}).get('card',{})
            environment_outdated=any(saved.get(k)!=card.get(k) for k in ('owner','environment_id','image','runtime','network_config_sha256','network','security_policy_sha256','account_definition'))
            return {'environment_outdated':environment_outdated,'stale':stale,'current_revision':current,'warning':warning or stale or environment_outdated,'state':'exported','revision':receipt['revision'],'exported_at':receipt['exported_at'],
                    'off_host_verified':False,'external_destination':self.destination!=self.folder/'portable-backups'}
        except (OSError,ValueError,KeyError,subprocess.SubprocessError):return {'state':'unavailable','off_host_verified':False}

    def helper(self,card,volumes):
        args=[*DOCKER,'run','--rm','-i','--network','none','--read-only','--user','1001:1001','--cap-drop','ALL',
              '--security-opt','no-new-privileges','--memory','1g','--pids-limit','80','--tmpfs','/tmp:rw,nosuid,nodev,size=640m,mode=1777']
        for name,target,readonly in volumes:
            args+=['--mount','type=volume,source='+name+',target='+target+(',readonly' if readonly else '')]
        return [*args,'--entrypoint','python3',card['image'],'-B','/opt/native/bundle_io.py']

    def export(self,owner):
        with self.broker.protection.lock_for(owner):
            card=self.broker.protection.control.load(owner);record=self.broker.protection.state(owner)
            if not record.get('backup_verified'):raise ValueError('verified_environment_backup_required')
            target=self.target(card);spec={'card':card,'snapshot':record['snapshot']}
            fd,temp=tempfile.mkstemp(prefix='.pending-',dir=target)
            try:
                with os.fdopen(fd,'wb') as out:
                    process=subprocess.Popen([*self.helper(card,[(card['backup'],'/backup',True)]),'export'],stdin=subprocess.PIPE,stdout=out,stderr=subprocess.PIPE)
                    with self.lock:
                        self.processes.add(process)
                        if self.stopping.is_set():process.terminate()
                    try:
                        _,errors=process.communicate(json.dumps(dict(spec,key=self.key())).encode()+b'\n',timeout=120)
                    finally:
                        if process.poll() is None:process.kill();process.wait()
                        with self.lock:self.processes.discard(process)

                    out.flush();os.fsync(out.fileno())
                if process.returncode:
                    try:code=json.loads(errors).get('error')
                    except (ValueError,TypeError):code=None
                    raise ValueError(code if code in {'backup_too_large','backup_expanded_too_large','checkpoint_changed_retry_export'} else 'backup_export_failed')
                details=json.loads(errors)
                file=uuid.uuid4().hex+'.cpab';final=target/file
                os.rename(temp,final)
                receipt={'spec':spec,'file':file,'revision':details['revision'],'sha256':digest_file(final),'exported_at':int(time.time())}
                write_json(target/'latest.json',receipt)
                return self.status(owner)
            finally:Path(temp).unlink(missing_ok=True)

    def prepare_restore(self,owner):
        control=self.broker.protection.control;card=read_json(control.card(owner))
        if card['owner']!=owner or card['image']!=control.image:raise ValueError('backup_card_changed')
        require_original_stopped(control,card)
        target=self.target(card);receipt=read_json(target/'latest.json');spec=receipt['spec']
        if any(spec['card'].get(k)!=card.get(k) for k in ('owner','environment_id','image','runtime','network_config_sha256','network','security_policy_sha256','account_definition')):raise ValueError('backup_card_changed')
        if not isinstance(receipt['file'],str) or Path(receipt['file']).name!=receipt['file']:raise ValueError('backup_file_invalid')
        package=target/receipt['file'];private(package)
        if digest_file(package)!=receipt['sha256']:raise ValueError('backup_package_changed')
        # If the local checkpoint survives, do not replace a newer credential.
        script="import json;from pathlib import Path;p=Path('/backup/credentials/latest.json');print(json.loads(p.read_text())['record']['revision'] if p.exists() else 0)"
        floor=self.folder/('credential-floor-'+owner+'.json')
        current=read_json(floor)['revision'] if floor.exists() else 0
        available=docker('volume','ls','--filter','name='+card['backup'],'-q').splitlines()
        if card['backup'] in available:
            current=max(current,int(docker('run','--rm','--network','none','--read-only','--user','1001:1001','--cap-drop','ALL',
                           '--mount','type=volume,source='+card['backup']+',target=/backup,readonly','--entrypoint','python3',card['image'],'-c',script)))
        if current>receipt['revision']:raise ValueError('backup_credentials_older_than_local')
        new=dict(card);created=[];container=None;committed=False
        try:
            suffix='-recovered-'+uuid.uuid4().hex[:8]
            for field in ('volume','backup','network_config'):
                new[field]=card[field]+suffix;docker('volume','create','--label','cpa.retention.id='+card['environment_id'],new[field]);created.append(new[field])
            args=self.helper(card,[(new['backup'],'/backup',False),(new['network_config'],'/network-config',False)])
            # Only encrypted bytes cross the host pipe; decryption and verification stay in a networkless helper.
            process=subprocess.Popen([*args,'restore'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                process.stdin.write(json.dumps(dict(spec,key=self.key(),minimum_revision=current)).encode()+b'\n')
                with package.open('rb') as source:
                    for block in iter(lambda:source.read(1024*1024),b''):process.stdin.write(block)
                process.stdin.close();process.stdin=None
                out,err=process.communicate(timeout=120)
                if process.returncode:raise ValueError('backup_restore_failed')
                restored=json.loads(out)
            finally:
                if process.poll() is None:process.kill();process.wait()
            sync_restored_volumes(new)
            control.helper(new,'restore',spec['snapshot'])
            container=docker('create',*control.args(new,runtime=True),new['image']);new['container']=container
            new['previous']={'container':card['container'],'volume':card['volume'],'backup':card['backup'],'network_config':card['network_config']}
            protection=dict(self.broker.protection.state(owner),phase='ready',backup_verified=True,
                            snapshot=spec['snapshot'],manifest_sha256=restored['manifest_sha256'])
            write_json(self.folder/('restore-'+owner+'.json'),{'old':card,'new':new,'protection':protection})
            committed=True
            return new
        finally:
            if not committed:
                if container:docker('rm','-f',container)
                for name in reversed(created):docker('volume','rm',name)

    def commit_restore(self,owner):
        journal=self.folder/('restore-'+owner+'.json')
        if not journal.exists():return False
        record=read_json(journal);old,new=record['old'],record['new'];control=self.broker.protection.control
        require_original_stopped(control,old)
        control.inspect(new)
        current=read_json(control.card(owner))
        if current not in (old,new):raise ValueError('restore_card_conflict')
        with self.broker.connect() as db:
            row=db.execute('SELECT container FROM bindings WHERE owner=?',(owner,)).fetchone()
            if not row or row[0] not in (old['container'],new['container']):raise ValueError('restore_binding_conflict')
            write_json(control.card(owner),new)
            db.execute('UPDATE bindings SET container=? WHERE owner=?',(new['container'],owner))
        write_json(self.broker.protection.record(owner),record['protection'])
        # A committed replacement may start only via the existing network-first entrypoint.
        control.start(owner);journal.unlink();return True

def digest_file(path):
    value=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):value.update(block)
    return value.hexdigest()

def require_original_stopped(control,card):
    ident=card['container']
    if len(ident)!=64 or any(c not in '0123456789abcdef' for c in ident):raise ValueError('container_id_invalid')
    present=docker('ps','-a','--no-trunc','--filter','id='+ident,'--format','{{.ID}}').splitlines()
    if not present:return
    if present!=[ident] or control.inspect(card)['State']['Running']:raise ValueError('stop_account_before_restore')

def sync_restored_volumes(card):
    script="""import os
from pathlib import Path
for root in (Path('/backup'),Path('/network-config')):
 for p in root.rglob('*'):
  if p.is_file():
   with p.open('rb') as stream:os.fsync(stream.fileno())
 for p in sorted([root]+[p for p in root.rglob('*') if p.is_dir()],key=lambda p:len(p.parts),reverse=True):
  fd=os.open(p,os.O_RDONLY|os.O_DIRECTORY)
  try:os.fsync(fd)
  finally:os.close(fd)
"""
    docker('run','--rm','--network','none','--read-only','--user','1001:1001','--cap-drop','ALL',
           '--mount','type=volume,source='+card['backup']+',target=/backup',
           '--mount','type=volume,source='+card['network_config']+',target=/network-config',
           '--entrypoint','python3',card['image'],'-c',script)

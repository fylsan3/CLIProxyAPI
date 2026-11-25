"""Opaque central-to-container bridge for the native, offline A/B worker only."""
import argparse,base64,hashlib,http.server,json,os,re,signal,socketserver,sqlite3,subprocess,sys,threading,time,uuid
from pathlib import Path

from runtime_guard import check_container,check_volume,PolicyError,body_object
from storage_guard import private_directory,private_file,prepare_socket,socket_permissions
from lifecycle import Lease,RequestWatch,finish_process
from accounting import UsageObserver,native_usage_observation,summarize
from message_body import read_message
from header_policy import request_headers,response_headers
from version import release_info
from account_registry import Registry,PROVIDERS
from account_identity import owner_for,valid_slug
from protection import Protection
from creation_progress import CreationFailure
from maintenance import MaintenanceGate
from browser_control import Browsers
from central_view import central_request,merge_central

ROOT=Path(__file__).resolve().parent
from host_runtime import docker_cli
CLI=docker_cli()
def docker(*args,timeout=15):
    return subprocess.check_output(CLI+list(args),stderr=subprocess.PIPE,text=True,timeout=timeout).strip()

class Broker:
    def __init__(self,folder):
        private_directory(folder);self.folder=folder
        self.lease=Lease(folder/'control.lock');self.stopping=threading.Event()
        self.image=json.loads((ROOT/'image.json').read_text())['id']
        self.registry=Registry(folder)
        from account_metadata import Metadata
        self.metadata=Metadata(folder)
        self.protection=Protection(folder/'environments')
        self.offline_only=self.protection.control.fixture.get('mode','closed_test')!='managed'
        self.browsers=Browsers(self,CLI)
        self.gate=MaintenanceGate()
        self.db=folder/'control.sqlite';private_file(self.db);self.lock=threading.RLock()
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS meta(scope TEXT)')
            if not db.execute('SELECT scope FROM meta').fetchone():db.execute('INSERT INTO meta VALUES(?)',(uuid.uuid4().hex[:12],))
            self.scope=db.execute('SELECT scope FROM meta').fetchone()[0]
            db.execute('CREATE TABLE IF NOT EXISTS bindings(owner TEXT PRIMARY KEY,container TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY,run TEXT,owner TEXT,container TEXT,state TEXT,status INTEGER,response TEXT,started INTEGER)')
            columns={row[1] for row in db.execute('PRAGMA table_info(attempts)')}
            if 'stop_reason' not in columns:db.execute('ALTER TABLE attempts ADD COLUMN stop_reason TEXT')
            for column in ('usage','input_sha256','ingress_sha256'):
                if column not in columns:db.execute('ALTER TABLE attempts ADD COLUMN '+column+' TEXT')
            db.execute("UPDATE attempts SET state='result_unknown' WHERE state IN ('running','preparing')")
        from portable_backup import Packages
        self.packages=Packages(self)
        for owner in self.registry.owners():
            self.packages.commit_restore(owner)
            self.protection.recover_creation(owner)
        self.browsers.recover()
    def available_providers(self):
        mode=self.protection.control.fixture.get('mode','closed_test')
        selected='mock-claude' if mode=='closed_test' else 'claude-subscription'
        return {selected:PROVIDERS[selected]}
    def central(self,action,body):return central_request(self.folder/'central-view.json',action,body)
    def dashboard(self,result):
        try:
            code,central=self.central('pool',{})
            if code!=200:central=None
        except (OSError,ValueError):central=None
        try:
            code,settings=self.central('logging-status',{})
            result['logging_to_file']=settings.get('logging-to-file') if code==200 else None
        except (OSError,ValueError):result['logging_to_file']=None
        return merge_central(result,central)
    def observe_backup_revision(self,owner,revision):
        if not hasattr(self,'packages') or type(revision) is not int or revision<1:return
        self.packages.observe_revision(owner,revision)
    def connect(self):return sqlite3.connect(self.db,timeout=3)
    def name(self,owner):return 'native-'+self.scope+'-'+owner.lower()
    def inspect(self,owner):
        with self.connect() as db:row=db.execute('SELECT container FROM bindings WHERE owner=?',(owner,)).fetchone()
        if not row:return None
        card=self.protection.control.load(owner)
        if card['container']!=row[0]:raise PolicyError('container_binding_mismatch')
        return self.protection.control.inspect(card)
    def create(self,owner,proxy_url):
        with self.lock:
            info=self.inspect(owner)
            if info:return self.status(owner)
            card=self.protection.create(owner,proxy_url)
            with self.connect() as db:db.execute('INSERT INTO bindings VALUES(?,?)',(owner,card['container']))
            return self.status(owner)
    def invoke(self,owner,path,body,connection=None):
        info=self.inspect(owner)
        if not info or info['State']['Status']!='running':raise PolicyError('worker_unavailable')
        process=subprocess.Popen(CLI+['exec','--user','1001:1001','-i',info['Id'],'/opt/native/worker','call'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        watch=None;timer=None
        try:
            process.stdin.write(json.dumps({'path':path,'body':body,'watch_input':True}).encode()+b'\n');process.stdin.flush()
            watch=RequestWatch(connection,process,self.stopping)
            timer=threading.Timer(35 if path.startswith('/auth/') else 3,finish_process,args=(process,));timer.daemon=True;timer.start()
            raw=process.stdout.read()
            if process.wait()!=0 or watch.cancelled.is_set():raise PolicyError('worker_call_interrupted')
        finally:
            if timer:timer.cancel()
            if watch:
                watch.close()
                if watch.cancelled.is_set():print(json.dumps({'event':'control_cancelled','owner':owner,'path':path,'reason':watch.reason}),flush=True)
            finish_process(process);process.stdout.close()
        frames=[json.loads(line) for line in raw.splitlines()]
        payload=b''.join(base64.b64decode(frame['body'],validate=True) for frame in frames if 'body' in frame)
        last=frames[-1]
        if not last.get('done') or last['owner']!=owner or last['container']!=info['Config']['Hostname'] or hashlib.sha256(payload).hexdigest()!=last['response_sha256']:
            raise PolicyError('receipt_mismatch')
        return frames[0]['status'],json.loads(payload)
    def _worker_status(self,owner):
        result={'slug':owner.lower(),'ready':False,'offline_only':self.offline_only}
        try:
            info=self.inspect(owner)
            if not info:return dict(result,reason='missing')
            result['container']=info['Id']
            if info['State']['Status']!='running':
                return dict(result,reason='container_stopped',exit_code=info['State'].get('ExitCode'))
            code,state=self.invoke(owner,'/health',{})
            if code!=200:return dict(result,reason='worker_unavailable')
            if state.get('authorized'):self.observe_backup_revision(owner,state.get('revision',0))
            identity=self.metadata.bind(owner.lower(),state.get('account_identity'))
            if identity:result['identity']=identity;result['label']=identity.get('email') or '已授权账号'
            issue='account_disabled' if self.metadata.route(owner.lower()).get('disabled') else state.get('dispatch_issue')
            reason=('authorization_pending' if issue=='authorization_required' and state.get('authorization_pending') else issue or ('offline_ready' if self.offline_only else 'account_ready'))
            return dict(result,state=state,reason=reason,ready=not issue,dispatch_mode='direct' if not issue else 'blocked')
        except (PolicyError,ValueError) as error:
            return dict(result,reason='worker_unavailable' if str(error) in ('worker_unavailable','worker_call_interrupted') else 'binding_check_failed')
        except (OSError,ValueError,KeyError,subprocess.SubprocessError):
            return dict(result,reason='worker_unavailable')
    def status(self,owner):
        gate=self.gate.status(owner)
        if gate['maintenance']:
            return dict(slug=owner.lower(),ready=False,reason='account_maintenance',dispatch_mode='blocked',offline_only=self.offline_only,protection=self.protection.state(owner),**gate)
        try:
            info=self.inspect(owner)
            if info and info['State']['Running']:
                network=self.protection.control.network_state(info)
                if not network['healthy']:
                    return {'slug':owner.lower(),'container':info['Id'],'ready':False,'reason':'account_proxy_unavailable','dispatch_mode':'blocked','network':network,'protection':self.protection.state(owner),'offline_only':self.offline_only}
        except (OSError,ValueError,KeyError,subprocess.SubprocessError):
            return {'slug':owner.lower(),'ready':False,'reason':'network_status_unknown','dispatch_mode':'blocked','offline_only':self.offline_only,'protection':self.protection.state(owner)}
        result=self._worker_status(owner)
        if info and info['State']['Running']:result['network']=network
        try:
            protection=self.protection.state(owner)
            result['protection']=protection
            if result.get('state',{}).get('authorized'):
                info=self.inspect(owner)
                if not self.protection.manifest_available(owner,info):
                    result.update(ready=False,reason='environment_backup_required',dispatch_mode='blocked')
            elif protection.get('phase') in ('saving_backup','verifying_backup','starting_protected_environment','backup_failed','checking_restore','recovery_check_failed'):
                result.update(ready=False,reason='environment_backup_required',dispatch_mode='blocked')
        except (OSError,ValueError,KeyError,subprocess.SubprocessError):
            result.update(ready=False,reason='environment_protection_unknown',dispatch_mode='blocked')
        return result
    def finalize_authorization(self,owner,body):
        with self.protection.lock_for(owner):
            try:
                state=self.invoke(owner,'/health',{})[1]
                if not state.get('authorized'):
                    self.protection.phase(owner,'exchanging_credentials',backup_verified=False)
                    code,result=self.invoke(owner,'/auth/complete',body)
                    if code!=200:
                        self.protection.phase(owner,'authorization_failed',backup_verified=False)
                        return code,result
                elif self.protection.state(owner).get('phase')=='ready':
                    return 200,self.status(owner)
                self.protection.complete_backup(owner,lambda:self.invoke(owner,'/health',{})[1])
                self.packages.note_revision(owner,self.invoke(owner,'/health',{})[1]['revision'])
                self.packages.enqueue(owner)
                return 200,self.status(owner)
            except Exception:
                self.protection.phase(owner,'backup_failed',backup_verified=False)
                return 503,{'error':{'message':'environment_backup_required'}}
    def retry_backup(self,owner):
        with self.protection.lock_for(owner):
            try:
                self.protection.complete_backup(owner,lambda:self.invoke(owner,'/health',{})[1])
                self.packages.note_revision(owner,self.invoke(owner,'/health',{})[1]['revision'])
                self.packages.enqueue(owner)
                return 200,self.status(owner)
            except Exception:
                self.protection.phase(owner,'backup_failed',backup_verified=False)
                return 503,{'error':{'message':'environment_backup_required'}}
    def admin(self,action,body,connection=None):
        protected={'refresh-check','refresh-execute','auth-begin','auth-cancel','open-browser','close-browser','retry-backup','backup-restore','account-update'}
        if action in protected:
            owner=self.registry.get(body.get('slug',''))['owner']
            try:
                with self.gate.request(owner):return self.admin_execute(action,body,connection)
            except ValueError as error:
                if str(error)=='account_maintenance':return 409,{'error':'account_maintenance'}
                raise
        return self.admin_execute(action,body,connection)

    def admin_execute(self,action,body,connection=None):
        if action=='register-auto':
            if set(body)!={'provider'} or body['provider'] not in self.available_providers():raise PolicyError('invalid_request')
            slug='account-'+uuid.uuid4().hex[:12]
            return 200,self.registry.register(slug,'待授权账号',body['provider'])
        if action=='route-update':
            slug=body.get('slug','');self.registry.get(slug)
            try:return 200,self.metadata.patch_route(slug,body.get('changes',{}),body.get('revision'))
            except ValueError as error:return 409,{'error':str(error)}
        if action=='register':
            if set(body)!={'slug','label','provider'}:raise PolicyError('invalid_request')
            if body['provider'] not in self.available_providers():raise ValueError('provider_not_available')
            return 200,self.registry.register(body['slug'],body['label'],body['provider'])
        if action=='backup-export':
            if set(body)!={'slug'} or not valid_slug(body['slug']):raise PolicyError('invalid_owner')
            self.packages.enqueue(self.registry.get(body['slug'])['owner']);return 202,{'queued':True}
        if action=='backup-restore':
            if set(body)!={'slug'} or not valid_slug(body['slug']):raise PolicyError('invalid_owner')
            owner=self.registry.get(body['slug'])['owner']
            try:
                with self.protection.lock_for(owner):
                    self.packages.prepare_restore(owner)
                    self.packages.commit_restore(owner)
            except ValueError as error:
                allowed={'stop_account_before_restore','backup_card_changed','backup_package_changed','backup_credentials_older_than_local','backup_restore_failed'}
                return 503,{'error':str(error) if str(error) in allowed else 'backup_restore_failed'}
            return 200,self.status(owner)
        if action=='dashboard':
            from dashboard import snapshot
            return 200,snapshot(self)
        if action=='ui-action':
            from dashboard import action as ui_action
            return ui_action(self,body)
        if action in ('logging-status','logging-update'):return self.central(action,body)
        if action=='list':return 200,{'projects':[dict(self.status(row['owner']),label=row['label'],provider=row['provider'],models=PROVIDERS[row['provider']]['models'],routing=self.metadata.route(row['slug'])) for row in self.registry.list()],'release':release_info(),'providers':self.available_providers(),'runtime_mode':self.protection.control.fixture.get('mode','closed_test')}
        if action=='summary':
            with self.connect() as db:
                totals=db.execute("SELECT COUNT(*),SUM(CASE WHEN state='completed' AND status>=200 AND status<300 THEN 1 ELSE 0 END),SUM(CASE WHEN state IN ('not_dispatched','result_unknown') OR status>=400 THEN 1 ELSE 0 END),SUM(CASE WHEN state IN ('preparing','running') THEN 1 ELSE 0 END),COUNT(DISTINCT run) FROM attempts").fetchone()
                recent={r[0]:r[1] for r in db.execute("SELECT owner,MAX(started) FROM attempts WHERE state='completed' AND status>=200 AND status<300 GROUP BY owner")}
            return 200,{'attempts':totals[0],'successful_attempts':totals[1] or 0,'failed_attempts':totals[2] or 0,'active_attempts':totals[3] or 0,'requests':totals[4],'last_success':recent}
        if action=='reconcile':
            with self.connect() as db:
                db.row_factory=sqlite3.Row
                groups=[]
                for row in db.execute('SELECT run,MAX(rowid) AS latest FROM attempts GROUP BY run ORDER BY latest DESC LIMIT 20'):
                    attempts=[dict(a) for a in db.execute('SELECT * FROM attempts WHERE run=? ORDER BY rowid LIMIT 101',(row['run'],))]
                    groups.append({'run':row['run'],'attempts':attempts[:100],'truncated':len(attempts)>100})
            return 200,{'requests':groups}
        if set(body)-{'slug','code','state','proxy_url'}:raise PolicyError('invalid_request')
        owner=self.registry.get(body.get('slug',''))['owner']
        if action=='proxy-view':return 200,{'proxy_url':self.protection.control.proxy_url(owner)}
        if action=='create':return 200,self.create(owner,body.get('proxy_url'))
        if action=='restart':
            try:
                with self.gate.maintenance(owner):
                    info=self.inspect(owner)
                    if info and info['State']['Running']:
                        code,state=self.invoke(owner,'/health',{})
                        if code!=200:raise ValueError('worker_unavailable')
                        if state.get('active_calls',0) or state.get('refreshing'):raise ValueError('account_busy')
                        if state.get('authorization_pending'):raise ValueError('authorization_pending')
                        self.browsers.close(owner)
                    self.protection.restart(owner)
            except ValueError as error:
                if str(error) in ('account_busy','account_maintenance','authorization_pending','worker_unavailable'):
                    return 409,{'error':str(error)}
                raise
            return 200,self.status(owner)
        if action=='retry-backup':return self.retry_backup(owner)
        if action=='open-browser':return 200,self.browsers.open(owner)
        if action=='close-browser':self.browsers.close(owner);return 200,{'browser':False}
        if action=='auth-cancel':return self.browsers.cancel(owner)
        if action=='auth-begin':
            state=self.invoke(owner,'/health',{})[1]
            if state.get('authorized'):raise PolicyError('already_authorized')
            self.protection.phase(owner,'authorizing',backup_verified=False)
            return self.browsers.begin(owner)
        if action=='account-statistics':
            with self.connect() as db:
                r=db.execute("SELECT COUNT(DISTINCT run),COUNT(*),SUM(CASE WHEN state='completed' AND status>=200 AND status<300 THEN 1 ELSE 0 END),SUM(CASE WHEN state IN ('not_dispatched','result_unknown') OR status>=400 THEN 1 ELSE 0 END) FROM attempts WHERE owner=?",(owner,)).fetchone()
            return 200,dict(zip(('requests','attempts','successful_attempts','failed_attempts'),[v or 0 for v in r]))
        if action=='usage':
            with self.connect() as db:
                db.row_factory=sqlite3.Row
                result=summarize(dict(row) for row in db.execute('SELECT state,usage FROM attempts WHERE owner=?',(owner,)))
            return 200,result
        if action=='history':
            with self.connect() as db:
                db.row_factory=sqlite3.Row
                rows=[dict(row) for row in db.execute('SELECT * FROM attempts WHERE owner=? ORDER BY started DESC,rowid DESC LIMIT 30',(owner,))]
            return 200,{'attempts':rows}
        if action=='auth-refresh':return self.central('refresh',{'slug':owner.lower()})
        if action=='account-update':return self.invoke(owner,'/auth/account-update',{},connection)
        if action=='refresh-check':
            code,result=self.invoke(owner,'/auth/refresh-check',{},connection)
            state=result.get('state',{})
            if code==200 and state.get('authorized'):self.observe_backup_revision(owner,state.get('revision',0))
            return code,result
        if action=='refresh-execute':
            code,_=self.invoke(owner,'/auth/refresh',{},connection)
            state_code,state=self.invoke(owner,'/health',{})
            if state_code!=200:raise PolicyError('worker_unavailable')
            if code==200 and state.get('authorized'):
                self.packages.note_revision(owner,state['revision'])
                self.packages.enqueue(owner)
            return 200,{'ok':code==200,'state':state}
        mapping={'auth-begin':'/auth/begin','auth-cancel':'/auth/cancel','auth-refresh':'/auth/refresh'}
        if action not in mapping:raise PolicyError('unknown_action')
        return self.invoke(owner,mapping[action],{k:body[k] for k in ('code','state') if k in body})

class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args):pass
    def answer(self,status,body):
        raw=json.dumps(body).encode();self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    def do_POST(self):
        self.close_connection=True
        self.connection.settimeout(4)
        try:
            is_message=self.path in ('/v1/messages','/v1/messages/count_tokens')
            if is_message:self.connection.settimeout(None)
            raw,body=(read_message if is_message else body_object)(self.headers,self.rfile);self.connection.settimeout(None)
            if is_message:return self.messages(raw,body)
            if not self.path.startswith('/admin/'):return self.answer(404,{})
            status,result=self.server.broker.admin(self.path[7:],body,self.connection);self.answer(status,result)
        except CreationFailure as error:self.answer(503,{'error':{'message':error.code}})
        except (PolicyError,OSError,ValueError,KeyError,subprocess.SubprocessError):self.answer(503,{'error':{'message':'native_worker_unavailable'}})
    def messages(self,raw,body):
        broker=self.server.broker
        slug=self.headers.get('X-Test-Project') or str(body.get('model','')).removeprefix('test-project-')
        try:owner=broker.registry.get(slug)['owner']
        except ValueError:return self.answer(400,{'error':'invalid_owner'})
        try:
            with broker.gate.request(owner):return self.execute_message(raw,body)
        except ValueError as error:
            if str(error)=='account_maintenance':return self.answer(503,{'error':{'message':'account_maintenance'}})
            raise
    def execute_message(self,raw,body):
        broker=self.server.broker
        selected=self.headers.get('X-Test-Project')
        slug=selected if selected is not None else str(body.get('model','')).removeprefix('test-project-')
        try:owner=broker.registry.get(slug)['owner']
        except ValueError:return self.answer(400,{'error':'invalid_owner'})
        if self.headers.get('X-Test-Model',body.get('model')) not in PROVIDERS[broker.registry.get(slug)['provider']]['models']:return self.answer(400,{'error':'model_not_bound_to_account'})
        run=self.headers.get('X-Test-Request','')
        if not re.fullmatch('[0-9a-f]{32}',run):return self.answer(400,{'error':'request_id_required'})
        attempt=uuid.uuid4().hex;stream=self.path=='/v1/messages' and (self.headers.get('X-Offline-Stream')=='true' or body.get('stream') is True);sent=False;done=False;completed=False
        input_hash=hashlib.sha256(json.dumps(body).encode()).hexdigest()
        with broker.connect() as db:db.execute('INSERT INTO attempts(id,run,owner,state,started,input_sha256,ingress_sha256) VALUES(?,?,?,?,?,?,?)',(attempt,run,owner,'preparing',int(time.time()),input_hash,hashlib.sha256(raw).hexdigest()))
        state=broker.status(owner);ident=state.get('container')
        reason='controller_stopping' if broker.stopping.is_set() else state['reason'] if not state.get('ready') else None
        if reason:
            with broker.connect() as db:db.execute("UPDATE attempts SET state='not_dispatched',container=?,status=503,stop_reason=? WHERE id=?",(ident,reason,attempt))
            return self.answer(503,{'error':{'message':reason}})
        with broker.connect() as db:db.execute("UPDATE attempts SET state='running',container=? WHERE id=?",(ident,attempt))
        receipt_host=broker.inspect(owner)['Config']['Hostname']
        observer=UsageObserver(stream);status=None;native_usage=''
        process=None;watch=None
        try:
            process=subprocess.Popen(CLI+['exec','--user','1001:1001','-i',ident,'/opt/native/worker','call'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
            process.stdin.write(json.dumps({'path':self.path,'body':body,'headers':request_headers(self.headers),'execution_config':self.headers.get('X-Offline-Execution-Config',''),'alt':self.headers.get('X-Offline-Alt',''),'model':self.headers.get('X-Offline-Model',''),'stream':stream,'source_format':self.headers.get('X-Offline-Source-Format',''),'response_format':self.headers.get('X-Offline-Response-Format',''),'run':run,'attempt':attempt,'watch_input':True}).encode()+b'\n');process.stdin.flush()
            watch=RequestWatch(self.connection,process,broker.stopping)
            first=json.loads(process.stdout.readline());status=first['status'];headers=first.get('headers',{})
            output=bytearray();digest=hashlib.sha256()
            def begin(chunked):
                self.send_response_only(status)
                for key,values in response_headers(headers).items():
                    for value in values:self.send_header(key,value)
                self.send_header('X-Test-Container',ident);self.send_header('X-Test-Attempt',attempt)
                if chunked:self.send_header('Transfer-Encoding','chunked');self.send_header('Trailer','X-Offline-Native-Usage')
                elif native_usage:self.send_header('X-Offline-Native-Usage',native_usage)
                if not chunked:self.send_header('Content-Length',str(len(output)));self.send_header('X-Test-Response-SHA256',digest.hexdigest())
                self.end_headers()
            if stream and status==200:begin(True);sent=True
            for line in process.stdout:
                frame=json.loads(line)
                if 'body' in frame:
                    chunk=base64.b64decode(frame['body'],validate=True);digest.update(chunk);observer.feed(chunk)
                    if sent:self.wfile.write(('%x\r\n'%len(chunk)).encode()+chunk+b'\r\n');self.wfile.flush()
                    else:
                        output.extend(chunk)
                elif frame.get('done'):
                    if (frame.get('owner'),frame.get('container'),frame.get('run'),frame.get('attempt'),frame.get('response_sha256'))!=(owner,receipt_host,run,attempt,digest.hexdigest()):raise PolicyError('receipt_mismatch')
                    if frame.get('input_sha256')!=input_hash:raise PolicyError('input_receipt_mismatch')
                    native_usage=frame.get('native_usage','')
                    if not isinstance(native_usage,str) or len(native_usage)>44000 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/' for c in native_usage):raise PolicyError('invalid_usage_receipt')
                    done=True
            if process.wait()!=0 or not done or watch.cancelled.is_set():raise PolicyError('worker_interrupted')
            with broker.connect() as db:db.execute("UPDATE attempts SET state='completed',status=?,response=?,usage=? WHERE id=?",(status,digest.hexdigest(),json.dumps(native_usage_observation(native_usage,observer.finish(True,status),status)),attempt))
            completed=True
            if sent:self.wfile.write(b'0\r\n'+(('X-Offline-Native-Usage: '+native_usage+'\r\n').encode() if native_usage else b'')+b'\r\n');self.wfile.flush()
            else:begin(False);self.wfile.write(output)
        except (OSError,ValueError,KeyError,PolicyError,subprocess.SubprocessError):
            with broker.connect() as db:
                if completed:db.execute("UPDATE attempts SET stop_reason='client_delivery_incomplete' WHERE id=?",(attempt,))
                else:db.execute("UPDATE attempts SET state='result_unknown',status=?,stop_reason=?,usage=? WHERE id=?",(status,watch.reason if watch and watch.cancelled.is_set() else 'execution_interrupted',json.dumps(observer.finish(False,status)),attempt))
            self.close_connection=True
            if not sent and not (watch and watch.cancelled.is_set()):
                try:self.answer(502,{'error':{'message':'native_execution_incomplete'}})
                except OSError:pass
        finally:
            if watch:watch.close()
            if process:
                finish_process(process)
                process.stdout.close()

class Server(socketserver.ThreadingMixIn,socketserver.UnixStreamServer):
    daemon_threads=False
    def get_request(self):
        connection,address=super().get_request();connection.settimeout(4);return connection,address
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory',type=Path);parser.add_argument('socket',type=Path);parser.add_argument('--dashboard-port',type=int);parser.add_argument('--control-group');args=parser.parse_args()
    group=__import__('grp').getgrnam(args.control_group).gr_gid if args.control_group else None
    os.umask(0o077);broker=Broker(args.directory);prepare_socket(args.socket,group)
    panel=None;panel_record=None
    if args.dashboard_port is not None:
        from panel import start_panel
        panel,panel_record=start_panel(broker,args.dashboard_port)
    with Server(str(args.socket),Handler) as server:
        server.broker=broker
        socket_permissions(args.socket,group)
        def shutdown(*unused):
            broker.stopping.set()
            threading.Thread(target=server.shutdown,daemon=True).start()
        signal.signal(signal.SIGTERM,shutdown);signal.signal(signal.SIGINT,shutdown)
        try:server.serve_forever(poll_interval=.1)
        finally:broker.stopping.set()
    if panel:panel.shutdown();panel.server_close();panel_record.unlink(missing_ok=True)
    broker.packages.close();broker.browsers.shutdown();args.socket.unlink(missing_ok=True);broker.protection.close();broker.lease.close()

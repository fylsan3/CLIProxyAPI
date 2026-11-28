"""Pinned official CLI, private local RPC, PTY, and opaque HTTPS CONNECT bridge."""
import base64,collections,fcntl,http.server,json,os,pty,re,select,signal,socket,socketserver,struct,subprocess,sys,termios,threading,time,uuid
from pathlib import Path
from urllib.parse import urlsplit
from claude_shared_auth import snapshot as shared_snapshot,status as shared_status

VERSION='2.1.331'
BINARY='/opt/claude-code/claude'
SOCKET='/tmp/claude-code.sock'
ROOT=Path('/state/claude-code')
MAX_SECONDS=7200
ACTIVE_STATES={'starting','running','cleaning'}

def check_network():
    from network_gate import check
    check()

def environment(credential=None):
    for name in ('home','config','workspace'):
        (ROOT/name).mkdir(mode=0o700,parents=True,exist_ok=True)
    env={k:os.environ[k] for k in ('PATH','TZ','LANG','LC_ALL','LANGUAGE','FIXTURE_OWNER','CPA_PROVIDER','PROXY_CONFIG_SHA256') if k in os.environ}
    env.update(HOME=str(ROOT/'home'),CLAUDE_CONFIG_DIR=str(ROOT/'config'),SHELL='/bin/bash',TERM='xterm-256color',
               HTTPS_PROXY='http://127.0.0.1:18080',HTTP_PROXY='http://127.0.0.1:18080',NO_PROXY='localhost,127.0.0.1,::1',
               BROWSER='/opt/native/claude_open_browser.py',DISABLE_AUTOUPDATER='1',CLAUDE_CODE_SKIP_UPDATE_CHECK='1',
               CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1')
    # Only a closed-test image invocation may select a mock endpoint/key.
    if os.environ.get('CPA_PROVIDER')=='mock-claude' and os.environ.get('CLAUDE_CODE_LOCAL_TEST')=='1':
        url=os.environ.get('CLAUDE_CODE_TEST_BASE_URL','')
        if urlsplit(url).hostname not in ('127.0.0.1','localhost'):raise ValueError('test_endpoint_not_local')
        env.update(ANTHROPIC_BASE_URL=url)
        # An isolated fixture may trust its own local mock TLS service.
        if Path('/bench/test-ca.crt').is_file():env['NODE_EXTRA_CA_CERTS']='/bench/test-ca.crt'
    if credential:env['CLAUDE_CODE_OAUTH_TOKEN']=credential.access_token
    return env

def group_alive(pgid):
    # Ignore zombies; the service is a Linux subreaper and reaps them below.
    if Path('/proc').is_dir():
        for entry in Path('/proc').glob('[0-9]*/stat'):
            try:
                fields=entry.read_text().rsplit(')',1)[1].split()
                if int(fields[2])==pgid and fields[0]!='Z':return True
            except (OSError,ValueError,IndexError):pass
        return False
    try:os.killpg(pgid,0);return True
    except ProcessLookupError:return False

def terminate(process):
    if not process:return
    # Every child has its own session. Clean its group even if the leader exited.
    # Callers serialize cleanup through the job/terminal owner thread.
    if getattr(process,'_cpa_cleaned',False):return
    for sig,grace in ((signal.SIGTERM,3),(signal.SIGKILL,1)):
        try:os.killpg(process.pid,sig)
        except ProcessLookupError:break
        deadline=time.monotonic()+grace
        while time.monotonic()<deadline:
            process.poll()
            if not group_alive(process.pid):break
            time.sleep(.05)
        if not group_alive(process.pid):break
    process.wait(timeout=1)
    # Adopted descendants in this job's process group only; never reap Go.
    while True:
        try:
            pid,_=os.waitpid(-process.pid,os.WNOHANG)
            if pid<=0:break
        except ChildProcessError:break
    if group_alive(process.pid):raise RuntimeError('claude_cleanup_incomplete')
    process._cpa_cleaned=True

def browser_open(url):
    u=urlsplit(url)
    routes={('claude.ai','/oauth/authorize'),('platform.claude.com','/oauth/authorize'),('claude.com','/cai/oauth/authorize')}
    if u.scheme!='https' or (u.hostname,u.path) not in routes or u.port not in (None,443) or u.username or u.password:
        raise ValueError('authorization_url_rejected')
    value=rpc('/tmp/fixture-control.sock',{'op':'open-claude-browser','url':url},timeout=40)
    if value.get('error'):raise ValueError('browser_open_failed')
    return {'ok':True}

def rpc(path,value,timeout=15):
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(timeout);s.connect(path);s.sendall(json.dumps(value).encode()+b'\n')
        line=s.makefile('rb').readline(16777217)
        if len(line)>16777216:raise ValueError('reply_too_large')
        return json.loads(line)

class Service:
    def __init__(self):
        self.lock=threading.RLock();self.jobs={};self.terminal=None;self.closing=False
        # Build verifies the pinned binary. Status/boot never executes Claude.
        self.version=VERSION+' (Claude Code)'
        if sys.platform=='linux':
            import ctypes
            if ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)!=0:raise OSError('subreaper_setup_failed')
    def busy(self):
        return any(j['state'] in ACTIVE_STATES for j in self.jobs.values())
    def terminal_running(self):
        return self.terminal and self.terminal['state'] in ACTIVE_STATES
    def lifecycle(self):
        if self.terminal_running():return self.terminal['state'],'terminal'
        for j in self.jobs.values():
            if j['state'] in ACTIVE_STATES:return j['state'],'api'
        return 'idle',None
    def dispatch(self,v):
        op=v.get('op')
        if op=='status':
            with self.lock:
                state,mode=self.lifecycle()
                return {'ok':True,'version':self.version,'version_source':'verified_build','state':state,'mode':mode,'busy':self.busy(),'terminal_running':bool(self.terminal_running()),'terminal_id':self.terminal['id'] if self.terminal_running() else None,'workspace':str(ROOT/'workspace'),'credentials_persistent':True,'authentication':shared_status(ROOT/'config')}
        if op=='browser-open':raise ValueError('use_go_authorization')
        if op=='job-start':return self.start_job(v)
        if op in ('job-read','job-cancel'):
            with self.lock:
                job=self.jobs.get(v.get('id'))
                if not job:raise ValueError('job_not_found')
                if op=='job-cancel' and job['state'] in ACTIVE_STATES:job['cancelled']=True
                return {k:job.get(k) for k in ('id','state','result','exit_code','error','credential_revision')}
        if op=='terminal-start':return self.start_terminal(v)
        if op in ('terminal-read','terminal-input','terminal-resize','terminal-stop'):
            with self.lock:
                t=self.terminal
                if not t or t['id']!=v.get('id'):raise ValueError('terminal_not_found')
                if op=='terminal-stop':t['stop'].set()
            if op=='terminal-stop':
                if not t['done'].wait(8) or t['state']!='closed':raise ValueError('terminal_cleanup_pending')
            with self.lock:
                if op=='terminal-input':
                    data=base64.b64decode(v.get('data',''),validate=True)
                    if len(data)>8192:raise ValueError('input_too_large')
                    if t['state']!='running':raise ValueError('terminal_closed')
                    os.write(t['fd'],data)
                if op=='terminal-resize':
                    if t['state']!='running':raise ValueError('terminal_closed')
                    self.resize(t['fd'],v)
                offset=v.get('offset',t['base'])
                if type(offset)!=int or offset<0:raise ValueError('invalid_offset')
                offset=max(offset,t['base']);start=min(offset-t['base'],len(t['output']))
                data=bytes(t['output'][start:start+32768])
                return {'id':t['id'],'state':t['state'],'data':base64.b64encode(data).decode(),'offset':offset+len(data),'base':t['base'],'exit_code':t['process'].poll() if t['done'].is_set() else None}
        raise ValueError('unsupported_operation')
    def start_job(self,v):
        prompt=v.get('prompt');model=v.get('model')
        if not isinstance(prompt,str) or not prompt.strip() or len(prompt.encode())>65536:raise ValueError('invalid_prompt')
        if model is not None and (not isinstance(model,str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',model)):raise ValueError('invalid_model')
        check_network();shared_snapshot(ROOT/'config')
        with self.lock:
            if self.closing:raise ValueError('claude_service_stopping')
            if self.busy() or self.terminal_running():raise ValueError('claude_busy_close_terminal_first')
            while len(self.jobs)>=8:self.jobs.pop(next(iter(self.jobs)))
            ident=uuid.uuid4().hex
            job={'id':ident,'state':'starting','result':None,'exit_code':None,'error':None,'cancelled':False,'process':None,'done':threading.Event()}
            self.jobs[ident]=job
            threading.Thread(target=self.run_job,args=(job,prompt,model),daemon=True).start()
            return {'id':ident,'state':'starting'}
    def run_job(self,job,prompt,model):
        p=None;result=None;error=None;outcome='failed'
        try:
            args=[BINARY,'-p','--output-format','stream-json','--verbose','--permission-mode','dontAsk','--tools','','--strict-mcp-config','--setting-sources','user','--no-session-persistence']
            if model:args+=['--model',model]
            credential=shared_snapshot(ROOT/'config')
            with self.lock:
                job['credential_revision']=credential.revision
                if job['cancelled'] or self.closing:return
                p=subprocess.Popen(args,env=environment(credential),cwd=ROOT/'workspace',stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
                job.update(process=p,state='running')
            # Nonblocking input keeps cancellation responsive even if CLI stops reading.
            os.set_blocking(p.stdin.fileno(),False);pending=memoryview(prompt.encode())
            output=bytearray();deadline=time.monotonic()+MAX_SECONDS;streams=[p.stdout,p.stderr]
            while streams or pending:
                if job['cancelled']:break
                if time.monotonic()>deadline:error='task_timeout';break
                ready,writable,_=select.select(streams,[p.stdin] if pending else [],[],.2)
                if writable:
                    try:pending=pending[os.write(p.stdin.fileno(),pending[:8192]):]
                    except BrokenPipeError:pending=memoryview(b'')
                    if not pending:p.stdin.close()
                for stream in ready:
                    chunk=os.read(stream.fileno(),65536)
                    if not chunk:streams.remove(stream);continue
                    if stream is p.stdout:
                        output.extend(chunk)
                        if len(output)>8*1024*1024:raise ValueError('cli_event_too_large')
                        while b'\n' in output:
                            line,_,rest=output.partition(b'\n');output=bytearray(rest)
                            try:event=json.loads(line)
                            except ValueError:continue
                            if isinstance(event,dict) and event.get('type')=='result':result=event
                # A stray descendant must not keep an exited CLI's pipes open.
                if p.poll() is not None:
                    with self.lock:job['state']='cleaning'
                    terminate(p)
                    if not ready:break
            if not job['cancelled'] and not error:
                p.wait(timeout=5)
                outcome='succeeded' if p.returncode==0 and result and not result.get('is_error') else 'failed'
                if outcome=='failed':error='claude_request_failed' if result else 'claude_result_missing'
        except Exception as e:error=str(e) if isinstance(e,ValueError) else 'claude_process_failed'
        finally:
            with self.lock:job['state']='cleaning'
            try:terminate(p)
            except Exception:
                # Fail closed: retain busy state if process cleanup cannot be proven.
                with self.lock:job['error']='claude_cleanup_incomplete'
                job['done'].set();return
            finally:
                if p:
                    for stream in (p.stdin,p.stdout,p.stderr):
                        if stream:stream.close()
            with self.lock:
                job.update(state='cancelled' if job['cancelled'] or self.closing else outcome,result=result,error=error,exit_code=p.returncode if p else None)
                job['done'].set()
    def resize(self,fd,v):
        cols,rows=v.get('cols',100),v.get('rows',30)
        if type(cols)!=int or type(rows)!=int or not 20<=cols<=300 or not 5<=rows<=100:raise ValueError('invalid_terminal_size')
        fcntl.ioctl(fd,termios.TIOCSWINSZ,struct.pack('HHHH',rows,cols,0,0))
    def start_terminal(self,v):
        mode=v.get('mode','interactive')
        if mode=='login':raise ValueError('use_go_authorization')
        if mode!='interactive':raise ValueError('invalid_terminal_mode')
        check_network();credential=shared_snapshot(ROOT/'config')
        with self.lock:
            if self.closing:raise ValueError('claude_service_stopping')
            if self.busy():raise ValueError('claude_busy')
            if self.terminal_running():
                if self.terminal['state']!='running':raise ValueError('terminal_cleanup_pending')
                return {'id':self.terminal['id'],'reused':True}
            master,slave=pty.openpty()
            def child():os.setsid();fcntl.ioctl(0,termios.TIOCSCTTY,0)
            try:
                self.resize(master,v)
                p=subprocess.Popen([BINARY],env=environment(credential),cwd=ROOT/'workspace',stdin=slave,stdout=slave,stderr=slave,preexec_fn=child)
            except Exception:os.close(master);raise
            finally:os.close(slave)
            t={'id':uuid.uuid4().hex,'mode':mode,'state':'running','process':p,'fd':master,'output':bytearray(),'base':0,'stop':threading.Event(),'done':threading.Event()};self.terminal=t
            threading.Thread(target=self.read_terminal,args=(t,),daemon=True).start()
            return {'id':t['id'],'reused':False}
    def read_terminal(self,t):
        try:
            while not t['stop'].is_set():
                ready,_,_=select.select([t['fd']],[],[],.2)
                if not ready:
                    if t['process'].poll() is not None:break
                    continue
                data=os.read(t['fd'],32768)
                if not data:break
                with self.lock:
                    t['output'].extend(data)
                    if len(t['output'])>524288:
                        n=len(t['output'])-524288;del t['output'][:n];t['base']+=n
        except OSError:pass
        finally:
            with self.lock:t['state']='cleaning'
            try:
                terminate(t['process'])
                with self.lock:t['state']='closed'
            except Exception:
                with self.lock:t['error']='claude_cleanup_incomplete'
            finally:
                with self.lock:os.close(t['fd']);t['done'].set()
    def close(self):
        with self.lock:
            self.closing=True;jobs=list(self.jobs.values());terminal=self.terminal
            for j in jobs:j['cancelled']=True
            if terminal:terminal['stop'].set()
        for j in jobs:j['done'].wait(8)
        if terminal:terminal['done'].wait(8)

def exact(s,n):
    data=b''
    while len(data)<n:
        chunk=s.recv(n-len(data))
        if not chunk:raise OSError('proxy_closed')
        data+=chunk
    return data

class Connect(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_CONNECT(self):
        upstream=None;established=False
        try:
            check_network();target=urlsplit('//'+self.path)
            host=target.hostname;port=target.port or 443
            if not host or target.username or target.password or target.path or port!=443:raise ValueError('invalid_connect_target')
            raw=host.encode('idna')
            if len(raw)>255:raise ValueError('invalid_host')
            upstream=socket.create_connection(('127.0.0.1',1080),timeout=10)
            upstream.sendall(b'\x05\x01\x00')
            if exact(upstream,2)!=b'\x05\x00':raise OSError('socks_failed')
            upstream.sendall(b'\x05\x01\x00\x03'+bytes([len(raw)])+raw+struct.pack('!H',port))
            head=exact(upstream,4)
            if head[:2]!=b'\x05\x00':raise OSError('socks_failed')
            exact(upstream,4 if head[3]==1 else 16 if head[3]==4 else exact(upstream,1)[0]);exact(upstream,2)
            self.send_response(200,'Connection Established');self.end_headers();self.wfile.flush()
            established=True
            upstream.settimeout(None);self.connection.settimeout(None)
            streams=[upstream,self.connection]
            while streams:
                ready,_,_=select.select(streams,[],[],1)
                for source in ready:
                    data=source.recv(65536);dest=self.connection if source is upstream else upstream
                    if not data:
                        streams.remove(source)
                        try:dest.shutdown(socket.SHUT_WR)
                        except OSError:pass
                    else:dest.sendall(data)
        except (OSError,ValueError):
            if not established:
                try:self.send_error(502,'Account proxy unavailable')
                except OSError:pass
        finally:
            if upstream:upstream.close()
            self.close_connection=True

class RPCHandler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            self.request.settimeout(45);raw=self.rfile.readline(131073)
            if len(raw)>131072:raise ValueError('request_too_large')
            v=json.loads(raw)
            if not isinstance(v,dict):raise ValueError('invalid_request')
            result=self.server.service.dispatch(v)
        except (ValueError,KeyError,TypeError,OSError) as e:
            result={'error':str(e) if isinstance(e,ValueError) else 'claude_service_unavailable'}
        self.wfile.write(json.dumps(result).encode()+b'\n')

class RPCServer(socketserver.ThreadingMixIn,socketserver.UnixStreamServer):daemon_threads=True

def serve():
    os.umask(0o077);check_network();service=Service()
    Path(SOCKET).unlink(missing_ok=True)
    server=RPCServer(SOCKET,RPCHandler);server.service=service;os.chmod(SOCKET,0o600)
    proxy=http.server.ThreadingHTTPServer(('127.0.0.1',18080),Connect)
    threading.Thread(target=proxy.serve_forever,daemon=True).start()
    def stop(*args):threading.Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    try:server.serve_forever(poll_interval=.2)
    finally:service.close();proxy.shutdown();server.server_close();Path(SOCKET).unlink(missing_ok=True)

if __name__=='__main__':
    if sys.argv[1:] == ['serve']:serve()
    elif sys.argv[1:] == ['call']:print(json.dumps(rpc(SOCKET,json.load(sys.stdin),timeout=45)))
    else:raise SystemExit('expected serve or call')

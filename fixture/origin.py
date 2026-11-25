"""Local protocol fixture for native CPA calls. No network sockets or real credentials."""
import html
import base64,subprocess
from urllib.parse import urlsplit, parse_qs, urlencode
import hashlib, http.server, json, os, select, socket, socketserver, threading, time
from pathlib import Path

owner=os.environ['FIXTURE_OWNER'];spec=json.loads(Path('/fixture/accounts.json').read_text())[owner]
root=Path('/mock')/owner;root.mkdir(exist_ok=True)
def fixturePath(name):return root/name
state=fixturePath('native-origin.json');evidence=fixturePath('native-evidence.jsonl')
lock=threading.RLock()
def save(value):
    tmp=state.with_suffix('.pending');tmp.write_text(json.dumps(value));tmp.replace(state)
def current():return json.loads(state.read_text()) if state.exists() else {'revision':0}
def token(revision):return 'sk-ant-oat01-offline-'+owner+'-'+str(revision)
def refresh(revision):return 'offline-refresh-'+owner+'-'+str(revision)
def record(value):
    with lock:
        with evidence.open('a') as out:out.write(json.dumps(value)+'\n')
class Server(http.server.ThreadingHTTPServer):daemon_threads=True
class Handler(http.server.BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args):pass
    def reply(self,status,value,kind='application/json'):
        raw=value if isinstance(value,bytes) else json.dumps(value,separators=(',',':')).encode()
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(raw)))
        self.send_header('Request-Id','req_offline_'+owner);self.end_headers();self.wfile.write(raw)
        return raw
    def do_GET(self):
        parsed=urlsplit(self.path)
        if parsed.path=='/manual-qr':
            png=subprocess.check_output(['qrencode','-o','-','-s','6','-m','4','CPA-OFFLINE-QR-'+owner])
            record({'owner':owner,'operation':'manual_qr'})
            return self.reply(200,('<html><title>Manual QR '+owner+'</title><button style="background:#11cc99;font-size:24px;padding:12px" onclick="window.close()">Close QR</button><br><img alt="Fictional QR" src="data:image/png;base64,'+base64.b64encode(png).decode()+'"></html>').encode(),'text/html')
        if parsed.path=='/oauth/authorize':
            q=parse_qs(parsed.query)
            if q.get('redirect_uri')!=['http://localhost:54545/callback'] or not q.get('state') or not q.get('code_challenge'):
                return self.reply(400,{'error':'invalid_authorization'})
            state=q['state'][0]
            record({'owner':owner,'operation':'browser_authorize','path':parsed.path})
            callback='http://localhost:54545/callback?'+urlencode({'state':state,'code':'offline-code-'+owner})
            cancel='http://localhost:54545/callback?'+urlencode({'state':state,'error':'access_denied'})
            if q.get('environment_report'):
                value=json.loads(q['environment_report'][0]);record({'owner':owner,'operation':'browser_environment','timezone':value['timezone'],'language':value['language']})
                return self.reply(200,{'ok':True})
            page=("<!doctype html><meta charset=utf-8><title>Test authorization "+owner+"</title>"
                  "<style>body{font:24px sans-serif;padding:40px}input,button,a{font-size:24px;margin:12px}</style>"
                  "<h1>Test authorization "+owner+"</h1><p>Fictional account only</p>"
                  "<script>const u=new URL(location);u.searchParams.set('environment_report',JSON.stringify({timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,language:navigator.language}));fetch(u);</script>"
                  "<label>Test input <input id='entry' style='background:#43ff09;width:220px'></label><button id='apply' style='background:#fb25de' onclick='result.textContent=entry.value;document.title=entry.value'>Apply</button><output id='result'></output>"
                  "<div style='display:inline-block;background:#cc55ff;width:240px;height:48px' onpointerdown='this.setPointerCapture(event.pointerId);this.dataset.start=event.clientX' onpointerup=\"if(event.clientX-Number(this.dataset.start)>60)document.title='DRAG-OK'\">Drag test</div>"
                  "<button style='background:#ff9900' onclick=\"window.open('/manual-qr','qr','width=420,height=420')\">Open QR</button>"
                  "<p><a id='approve' style='display:inline-block;background:#00aaff;padding:14px' href='"+html.escape(callback,quote=True)+"'>Authorize "+owner+"</a></p>"
                  "<p><a id='deny' style='display:inline-block;background:#ff4040;padding:14px' href='"+html.escape(cancel,quote=True)+"'>Cancel authorization</a></p>")
            return self.reply(200,page.encode(),'text/html; charset=utf-8')
        if self.path=='/location-check':
            record({'owner':owner,'operation':'location_check'})
            if fixturePath('bad-location').exists():return self.reply(200,{'success':True,'ip':'203.0.113.1','timezone':{'id':'Invalid/Test'}})
            return self.reply(200,{'success':True,'ip':spec['egress'],'timezone':{'id':spec['timezone']}})
        if self.path=='/network-check':
            record({'owner':owner,'operation':'network_check'})
            return self.reply(200,{'owner':owner,'egress':'203.0.113.99' if fixturePath('wrong-egress').exists() else spec['egress']})
        if self.path=='/browser':
            record({'owner':owner,'operation':'browser','path':self.path})
            return self.reply(200,('<html><title>SOCKS-BROWSER-'+owner+'</title><body>SOCKS '+owner+'</body></html>').encode(),'text/html')
        if self.headers.get('Authorization')!='Bearer '+token(current()['revision']):return self.reply(401,{'error':'offline_token_required'})
        record({'owner':owner,'operation':'profile' if self.path.endswith('profile') else 'roles','path':self.path,'header_names':sorted(self.headers.keys())})
        if self.path=='/api/oauth/profile':return self.reply(200,{'account':{'uuid':'offline-account-'+owner,'email':owner+'@example.invalid'},'organization':{'uuid':'offline-org-'+owner,'name':'Offline'}})
        if self.path=='/api/oauth/claude_cli/roles':return self.reply(200,{'roles':['offline']})
        self.reply(404,{})
    def do_POST(self):
        size=int(self.headers.get('Content-Length','0'))
        if not 0<size<1000000:return self.reply(400,{})
        raw=self.rfile.read(size)
        try:body=json.loads(raw)
        except ValueError:return self.reply(400,{'error':'invalid_json'})
        if self.path=='/v1/oauth/token':
            with lock:
                data=current();grant=body.get('grant_type')
                if grant=='authorization_code':
                    if body.get('code')!='offline-code-'+owner or not body.get('code_verifier') or not body.get('state'):
                        return self.reply(400,{'error':'invalid_grant'})
                    data['revision']=1
                elif grant=='refresh_token':
                    policy_path=fixturePath('offline-refresh-policy.json')
                    policy=json.loads(policy_path.read_text()) if policy_path.exists() else {}
                    record({'owner':owner,'operation':'refresh_attempt'})
                    if policy.get('hold'):
                        lock.release()
                        try:
                            for _ in range(400):
                                if fixturePath('release-offline-refresh').exists():break
                                ready,_,_=select.select([self.connection],[],[],0)
                                if ready and not self.connection.recv(1,socket.MSG_PEEK):
                                    record({'owner':owner,'operation':'refresh_cancelled'});self.close_connection=True;return
                                time.sleep(.05)
                            else:return self.reply(503,{'error':'fixture_release_timeout'})
                        finally:lock.acquire()
                    if policy.get('delay_seconds'):time.sleep(min(float(policy['delay_seconds']),5))
                    if policy.get('revoked'):return self.reply(401,{'error':'token_revoked'})
                    if policy.get('temporary'):return self.reply(503,{'error':'temporarily_unavailable'})
                    if policy.get('reject'):return self.reply(400,{'error':'invalid_grant'})
                    if policy.get('disconnect'):
                        self.close_connection=True;return
                    if body.get('refresh_token')!=refresh(data['revision']):return self.reply(400,{'error':'invalid_grant'})
                    data['revision']+=1
                else:return self.reply(400,{'error':'invalid_grant'})
                save(data);revision=data['revision']
            record({'owner':owner,'operation':grant,'path':self.path,'body_fields':list(body),'header_names':sorted(self.headers.keys()),'revision':revision})
            return self.reply(200,{'access_token':token(revision),'refresh_token':refresh(revision),'token_type':'Bearer','expires_in':28800,
                'account':{'uuid':'offline-account-'+owner,'email_address':owner+'@example.invalid'},'organization':{'uuid':'offline-org-'+owner,'name':'Offline'}})
        if self.path.split('?')[0]!='/v1/messages':return self.reply(404,{})
        if self.headers.get('Authorization')!='Bearer '+token(current()['revision']):return self.reply(401,{'type':'error','error':{'type':'authentication_error','message':'offline token required'}})
        content=body.get('messages',[{}])[-1].get('content','')
        case=content if isinstance(content,str) else ''.join(x.get('text','') for x in content if isinstance(x,dict))
        if case in ('wait_headers','wait_stream','broken_stream'):
            if case!='wait_headers':
                data=b'event: message_start\ndata: {"type":"message_start","message":{"id":"offline","type":"message","role":"assistant","model":"fixture","content":[],"usage":{"input_tokens":1,"output_tokens":0}}}\n\n'
                self.send_response(200);self.send_header('Content-Type','text/event-stream')
                self.send_header('Content-Length',str(len(data)+9999));self.end_headers()
                self.wfile.write(data);self.wfile.flush()
            record({'owner':owner,'run':self.headers.get('X-Offline-Run'),'attempt':self.headers.get('X-Offline-Attempt'),'operation':'lifecycle_wait','case':case})
            if case=='broken_stream':self.close_connection=True;return
            while True:
                ready,_,_=select.select([self.connection],[],[],.1)
                if ready:
                    try:closed=not self.connection.recv(1,socket.MSG_PEEK)
                    except OSError:closed=True
                    if closed:
                        record({'owner':owner,'operation':'lifecycle_cancelled','case':case})
                        self.close_connection=True;return
        unauthorized=case=='unauthorized_always' or (case=='unauthorized_once' and not fixturePath('once401').exists())
        if unauthorized:fixturePath('once401').touch()
        status=401 if unauthorized else 503 if case=='failover' and owner=='A' else 403 if case=='denied' else 429 if case=='limit' else 200
        response={'id':'msg_offline_'+owner,'type':'message','role':'assistant','model':body['model'],
                  'content':[{'type':'text','text':owner+' native OK'}],'stop_reason':'end_turn','stop_sequence':None,'usage':{'input_tokens':9,'output_tokens':3}}
        if case=='cache':response['usage'].update(cache_creation_input_tokens=4,cache_read_input_tokens=7)
        if case=='no_usage':response.pop('usage')
        if case=='tool':response.update(content=[{'type':'tool_use','id':'toolu_offline','name':'read_file','input':{'path':'/workspace/fixture.txt'}}],stop_reason='tool_use')
        if status!=200:response={'type':'error','error':{'type':'authentication_error' if status==401 else 'permission_error' if status==403 else 'rate_limit_error','message':'offline '+case}}
        chunks=[json.dumps(response,separators=(',',':')).encode()+b'\n'];kind='application/json'
        if body.get('stream') and status==200:
            events=[('message_start',{'message':dict(response,content=[],stop_reason=None)}),
                    ('content_block_start',{'index':0,'content_block':{'type':'text','text':''}}),
                    ('content_block_delta',{'index':0,'delta':{'type':'text_delta','text':owner+' native OK'}}),
                    ('content_block_stop',{'index':0}),
                    ('message_delta',{'delta':{'stop_reason':'end_turn','stop_sequence':None},'usage':{'output_tokens':3}}),('message_stop',{})]
            chunks=[('event: '+name+'\ndata: '+json.dumps(dict(data,type=name),separators=(',',':'))+'\n\n').encode() for name,data in events]
            kind='text/event-stream'
        response_raw=b''.join(chunks)
        record({'owner':owner,'run':self.headers.get('X-Offline-Run'),'attempt':self.headers.get('X-Offline-Attempt'),'operation':'messages','path':self.path,'case':case,'status':status,'stream':bool(body.get('stream')),
                'header_names':sorted(self.headers.keys()),'body_fields':list(body),'input_sha256':hashlib.sha256(raw).hexdigest(),
                'response_sha256':hashlib.sha256(response_raw).hexdigest(),'revision':current()['revision'],
                'system':body.get('system'),'metadata_fields':list((body.get('metadata') or {}).keys())})
        self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(response_raw)));self.send_header('Request-Id','req_offline_'+owner)
        if fixturePath('quota-headers.json').exists():
            for name,value in json.loads(fixturePath('quota-headers.json').read_text()).items():self.send_header(name,value)
        self.end_headers()
        try:
            for i,chunk in enumerate(chunks):
                self.wfile.write(chunk);self.wfile.flush()
                if i==0 and case=='hold_stream' and body.get('stream'):
                    record({'owner':owner,'operation':'stream_started'})
                    for _ in range(500):
                        if fixturePath('release-stream').exists():break
                        time.sleep(.05)
                    else:raise TimeoutError('fixture_stream_not_released')
        except (BrokenPipeError,ConnectionResetError):pass

os.umask(0o077)
with Server(('0.0.0.0',spec['origin_port']),Handler) as server:server.serve_forever()

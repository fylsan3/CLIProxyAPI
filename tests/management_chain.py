"""Exercise the real transport branch against closed HTTPS fixtures, without real accounts."""
import concurrent.futures,threading
from contextlib import suppress
import base64,gzip,hashlib,http.client,json,subprocess,tempfile,time,traceback,uuid
from pathlib import Path
from urllib.parse import urlsplit
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from lab_support import ROOT,CLI,docker,stop
def wait(fn):
 for _ in range(200):
  try:
   value=fn()
   if value:return value
  except (OSError,ValueError,subprocess.SubprocessError):pass
  time.sleep(.2)
 raise RuntimeError('provider_test_wait_timeout')

# The script runs as the account user, uses the loopback SOCKS adapter and trusts
# only the test image's certificate store. It never prints an OAuth URL or code.
AUTHORIZE = r'''
import html,json,http.client,socket,ssl,struct,sys
from html.parser import HTMLParser
from urllib.parse import urlsplit
u=urlsplit(json.load(sys.stdin)['url'])
assert u.scheme=='https' and u.netloc=='claude.ai'
s=socket.create_connection(('127.0.0.1',1080),timeout=10)
def recv(n):
 b=b''
 while len(b)<n:
  p=s.recv(n-len(b));assert p;b+=p
 return b
s.sendall(b'\x05\x01\x00');assert recv(2)==b'\x05\x00'
h=u.hostname.encode();s.sendall(b'\x05\x01\x00\x03'+bytes([len(h)])+h+struct.pack('!H',443))
assert recv(3)==b'\x05\x00\x00';kind=recv(1)[0];recv(4 if kind==1 else 16 if kind==4 else recv(1)[0]);recv(2)
s=ssl.create_default_context().wrap_socket(s,server_hostname=u.hostname)
c=http.client.HTTPConnection(u.hostname);c.sock=s;c.request('GET',u.path+'?'+u.query)
r=c.getresponse();assert r.status==200;page=r.read().decode();c.close()
class Links(HTMLParser):
 def handle_starttag(self,tag,attrs):
  a=dict(attrs)
  if a.get('id')=='approve':self.target=a['href']
p=Links();p.feed(page);v=urlsplit(p.target);assert v.hostname=='localhost' and v.port==54545
c=http.client.HTTPConnection('127.0.0.1',54545,timeout=10);c.request('GET',v.path+'?'+v.query)
r=c.getresponse();r.read();assert r.status==302 and r.getheader('Location')=='/success';c.close();print('callback_complete')
'''

def run():
 report={'real_accounts_used':False,'published':False,'browser_interaction_tested':False,'cases':{}}
 scope=uuid.uuid4().hex[:12];network='cpa-headers-'+scope;fixture=None;process=None
 images=json.loads((ROOT/'image.json').read_text());specs=json.loads((ROOT/'tls-fixture/accounts.json').read_text())
 with tempfile.TemporaryDirectory(prefix='cpa-provider-',dir='/tmp') as folder:
  state=Path(folder).resolve();state.chmod(0o700)
  try:
   docker('network','create','--internal','--label','cpa.socks-lab='+scope,network)
   fixture=docker('run','-d','--pull=never','--network',network,'--read-only','--cap-drop','ALL','--tmpfs','/tmp:mode=1777','--tmpfs','/mock:mode=1777',images['tls_fixture'])
   ip=json.loads(docker('inspect',fixture))[0]['NetworkSettings']['Networks'][network]['IPAddress']
   definition=state/'fixture.json';definition.write_text(json.dumps({'mode':'closed_tls_test','scope':scope,'network':network,'ip':ip,'accounts':specs}));definition.chmod(0o600)
   destination=state/'backup-test';destination.mkdir(mode=0o700)
   from saved_config import prepare
   cfgpath,_,_,_=prepare(ROOT,state,max_request_body_bytes=524288)
   cfg=json.loads(cfgpath.read_text());cfg['disable-cooling']=True;cfg['payload']={'override':[{'models':[{'name':'claude-*'}],'params':{'max_tokens':23}}]}
   cfgpath.write_text(json.dumps(cfg))
   with (state/'launch.log').open('ab') as log:
    process=subprocess.Popen(['python3','-B',str(ROOT/'launch.py'),'--state',str(state),'--ephemeral','--network-fixture',str(definition),'--backup-directory',str(destination),'--max-request-body-bytes','524288'],stdout=log,stderr=log)
   wait(lambda:(state/'launch.json').exists())
   launch=json.loads((state/'launch.json').read_text());ui=urlsplit(launch['management_url']);api=urlsplit(launch['api_base']);key=Path(launch['api_key_file']).read_text().strip()
   def panel(method,path,body=None):
    c=http.client.HTTPConnection('127.0.0.1',ui.port,timeout=90)
    try:
     c.request(method,'/v8/management/account-environments'+path,json.dumps(body) if body is not None else None,{'Content-Type':'application/json','Origin':'http://127.0.0.1:'+str(ui.port),'Authorization':'Bearer '+key})
     r=c.getresponse();return r.status,json.loads(r.read() or b'{}')
    finally:c.close()
   def action(op,owner,**values):
    code,data=panel('POST','/action',dict(action=op,slug=owner.lower(),**values));assert code==200,(op,code,data);return data
   def project(owner):
    code,value=panel('GET','/snapshot');assert code==200
    return next(p for p in value['projects'] if p['slug']==owner.lower())
   def evidence(owner):
    return json.loads(docker('exec',fixture,'python3','-c',"import json;from pathlib import Path;p=Path('/mock/"+owner+"/native-evidence.jsonl');print(json.dumps([json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []))"))
   cards={}
   def worker(owner,path,body=None):
    p=subprocess.run(CLI+['exec','--user','1001:1001','-i',cards[owner]['container'],'/opt/native/worker','call'],input=json.dumps({'path':path,'body':body or {}})+'\n',capture_output=True,text=True,timeout=40,check=True)
    frames=[json.loads(line) for line in p.stdout.splitlines()];raw=b''.join(base64.b64decode(f['body']) for f in frames if 'body' in f)
    assert hashlib.sha256(raw).hexdigest()==frames[-1]['response_sha256'];return frames[0]['status'],json.loads(raw)
   for owner in ('A','B'):
    action('register',owner,label='HTTPS 测试 '+owner,provider='claude-subscription')
    action('create',owner,proxy_url='socks5h://test-'+owner+':fixture-password-'+owner+'@'+ip+':'+str(specs[owner]['proxy_port']))
    cards[owner]=json.loads((state/'broker-private/environments'/(owner+'.json')).read_text())
    wait(lambda:worker(owner,'/health')[0]==200)
    code,pending=worker(owner,'/auth/begin');assert code==200
    assert urlsplit(pending['authorization_url']).netloc=='claude.ai'
    p=subprocess.run(CLI+['exec','--user','1001:1001','-i',cards[owner]['container'],'python3','-B','-c',AUTHORIZE],input=json.dumps({'url':pending['authorization_url']}),text=True,capture_output=True,timeout=30)
    assert p.returncode==0,p.stderr[-1000:]
    wait(lambda:worker(owner,'/health')[1].get('authorized'))
    action('retry-backup',owner);wait(lambda:project(owner).get('overall_ready'))
    assert worker(owner,'/health')[1]['revision']==1
    print('Authorized fictional '+owner,flush=True)
   def management(method,path,body=None):
    c=http.client.HTTPConnection('127.0.0.1',ui.port,timeout=90)
    try:
     c.request(method,'/v8/management'+path,json.dumps(body) if body is not None else None,{'Authorization':'Bearer '+key,'Content-Type':'application/json'})
     r=c.getresponse();return r.status,json.loads(r.read() or b'{}')
    finally:c.close()
   code,creds=management('GET','/credentials');assert code==200 and len(creds['files'])==2,creds
   assert {a['email'] for a in creds['files']}=={'A@example.invalid','B@example.invalid'}
   assert all('access_token' not in json.dumps(a) for a in creds['files'])
   assert management('PATCH','/credentials/fields',{'name':'a','priority':10,'weight':7})[0]==200
   code,creds=management('GET','/credentials');a=next(a for a in creds['files'] if a['name']=='a');assert a['priority']==10 and a['weight']==7
   assert management('PATCH','/credentials/fields',{'name':'a','priority':0,'route_revision':0})[0]==409
   assert management('GET','/credentials/models?name=a')[1]['models']
   assert management('POST','/routing/cooldown/reset',{'auth_index':a['auth_index']})[0]==200
   assert management('PATCH','/credentials/fields',{'name':'a','access_token':'not-allowed'})[0]==400
   updated=action('account-update','A');assert updated['ok'] and updated['account_observation']['usage']['values']['five_hour']['utilization']==17,updated
   assert project('A')['identity']['email']=='A@example.invalid'
   docker('exec',fixture,'touch','/mock/A/usage-denied')
   updated=action('account-update','A');assert updated['partial'] and updated['account_observation']['usage']['error']=='upstream_query_failed'
   assert updated['account_observation']['usage']['values']['five_hour']['utilization']==17
   assert project('A')['overall_ready'] and project('B')['overall_ready']
   docker('exec',fixture,'rm','/mock/A/usage-denied')
   assert action('account-update','B')['ok']
   assert management('PATCH','/credentials/fields',{'name':'a','priority':0,'weight':1})[0]==200
   report['cases']['account_metadata_native_routing_and_partial_update']={'passed':True,'real_profile_permissions_verified':False}
   catalog=[m['id'] for m in json.loads((ROOT/'models.json').read_text())]
   report['catalog_count']=len(catalog)
   def request(owner='A',content='ordinary',model='claude-sonnet-4-6',path='/v1/messages',stream=False,body=None,compressed=False,chunked=False,extra_headers=None):
    payload=body or {'model':model,'max_tokens':16,'stream':stream,'messages':[{'role':'user','content':content}]}
    raw=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
    headers={'Authorization':'Bearer '+key,'X-Test-Pin':owner.lower(),'Content-Type':'application/json'}
    if extra_headers:headers.update(extra_headers)
    if compressed:raw=gzip.compress(raw);headers['Content-Encoding']='gzip'
    c=http.client.HTTPConnection('127.0.0.1',api.port,timeout=3800)
    try:
     c.request('POST',path,[raw[:100],raw[100:]] if chunked else raw,headers,encode_chunked=chunked)
     response=c.getresponse();result=response.read();return response.status,result,{name.lower():response.headers.get_all(name) for name in response.headers.keys()}
    finally:c.close()
   assert management('PATCH','/credentials/fields',{'name':'b','priority':20})[0]==200
   status,body,headers=request(extra_headers={'X-Test-Pin':''});assert status==200 and b'B' in body,(status,body[:300])
   assert management('PATCH','/credentials/fields',{'name':'b','priority':0})[0]==200
   report['cases']['priority_dispatch_real_selector']=True
   def call(owner='A',**kwargs):
    code,raw,headers=request(owner,**kwargs);assert code==200,(code,raw[:150]);return raw,headers
   def last(owner,op='messages'):
    return [e for e in evidence(owner) if e['operation']==op][-1]
   def calls():return sum(e['operation'] in ('messages','count_tokens') for o in ('A','B') for e in evidence(o))
   def check(owner,**kwargs):
    raw,headers=call(owner,**kwargs);event=last(owner)
    assert event['response_sha256']==hashlib.sha256(raw).hexdigest()
    assert headers.get('X-Test-Container')==cards[owner]['container']
    return raw
   def assert_response(owner,code,raw,h,status=200,op='messages'):
    assert code==status,(code,raw[:200])
    event=last(owner,op)
    assert hashlib.sha256(raw).hexdigest()==event['response_sha256']
    assert len(h.get('server',[]))==1 and len(h.get('date',[]))==1,h
    assert h.get('x-feature-owner')==[owner],h
    assert h.get('x-feature-value')==['first','second'],h
    assert h.get('retry-after')==['2'],h
    assert h.get('anthropic-ratelimit-requests-remaining')==['17'],h
    assert h.get('x-litellm-test')==['preserved'],h
    assert h.get('x-test-container')==[cards[owner]['container']],h
    assert not any(n in h for n in ('set-cookie','x-hop-only','x-offline-owner')),h
   def admin(method,path,body=None):
    c=http.client.HTTPConnection('127.0.0.1',api.port,timeout=40)
    try:
     c.request(method,'/v8/management/'+path,json.dumps(body) if body is not None else None,{'Authorization':'Bearer '+key,'Content-Type':'application/json'})
     r=c.getresponse();return r.status,json.loads(r.read())
    finally:c.close()
   if '--remaining' not in sys.argv:
    revisions={o:worker(o,'/health')[1]['revision'] for o in ('A','B')}
    # Changing routing updates the actual existing container pool, not a new manager.
    assert admin('PUT','config/routing/strategy','fill-first')[0]==200
    wait(lambda:panel('GET','/snapshot')[1].get('scheduler_config',{}).get('strategy')=='fill-first')
    assert admin('PUT','config/routing/retry/request-retry',1)[0]==200
    wait(lambda:panel('GET','/snapshot')[1].get('scheduler_config',{}).get('request_retry')==1)
    report['cases']['routing_retry_hot_update']=True
    assert admin('POST','oauth/auth-url',{'provider':'claude'})[0]==409
    report['cases']['native_authorization_not_started']=True
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
     held=pool.submit(request,'A',content='hold_stream',stream=True)
     wait(lambda:any(e.get('operation')=='stream_started' for e in evidence('A')))
     code,value=admin('GET','observability/requests/in-flight');assert code==200 and value['in_flight']>=1,value
     busy=panel('GET','/snapshot')[1]
     assert busy['scheduler_in_flight']>=1
     assert next(p for p in busy['projects'] if p['slug']=='a')['state']['active_calls']>=1
     assert any(a['owner']=='A' and a['container']==cards['A']['container'] and a['state']=='running' for r in busy['requests'] for a in r['attempts'])
     code,value=panel('POST','/action',{'action':'restart','slug':'a'});assert code==409 and value['error']=='account_busy',(code,value)
     assert request('B')[0]==200
     docker('exec',fixture,'python3','-c',"from pathlib import Path;Path('/mock/A/release-stream').touch()")
     assert held.result()[0]==200
    wait(lambda:admin('GET','observability/requests/in-flight')[1]['in_flight']==0)
    assert all(worker(o,'/health')[1]['revision']==revisions[o] for o in ('A','B'))
    report['cases'].update(busy_restart_refused=True,B_stream_period_usable=True,actual_combined_in_flight=True)
   before=worker('A','/health')[1]['revision']
   viewer=action('open-browser','A');assert viewer['viewer_url']
   assert worker('A','/health')[1]['revision']==before
   viewer2=action('open-browser','A');assert viewer2['viewer_url']==viewer['viewer_url']
   if '--interactive' in sys.argv:
    preview=ROOT/'evidence/test-browser-preview.json';preview.write_text(json.dumps(viewer));preview.chmod(0o600)
    marker=ROOT/'evidence/test-browser-preview-done';marker.unlink(missing_ok=True)
    print('Fictional browser ready for UI check',flush=True)
    deadline=time.monotonic()+180
    while not marker.exists() and time.monotonic()<deadline:time.sleep(.2)
    report['browser_interaction_tested']=marker.exists()
    preview.unlink(missing_ok=True);marker.unlink(missing_ok=True)
   action('close-browser','A');action('restart','A');wait(lambda:project('A').get('overall_ready'))
   assert worker('A','/health')[1]['revision']==before
   assert request('A')[0]==200
   assert request('B')[0]==200
   report['cases'].update(authorized_browser_reentry_same_session=True,restart_preserves_credentials=True,request_after_restart=True)
   from worker_sample import arm,collect
   from request_sample import CaptureServer,Recording
   for case,stream,expected in [('ordinary',False,200),('denied',False,403),('ordinary',True,200)]:
    payload={'model':'claude-sonnet-4-6','max_tokens':16,'stream':stream,'messages':[{'role':'user','content':case}]}
    raw=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
    mark=arm(cards['A']['container'],raw)
    recorder=Recording(state/('ingress-'+mark['id']),'fixture-sample');proxy=CaptureServer('http://127.0.0.1:'+str(api.port),recorder)
    threading.Thread(target=proxy.serve_forever,daemon=True).start()
    try:
     c=http.client.HTTPConnection('127.0.0.1',proxy.server_port,timeout=120);c.request('POST','/v1/messages',raw,{'Authorization':'Bearer '+key,'X-Test-Pin':'a','X-CPA-Sample':'fixture-sample','Content-Type':'application/json'})
     r=c.getresponse();reply=r.read();assert r.status==expected,(r.status,reply[:100]);c.close()
     found=wait(lambda:list((state/('ingress-'+mark['id'])).glob('sample-*/record.json')))
     assert (found[0].parent/'request.bin').read_bytes()==raw
     assert (found[0].parent/'response.bin').read_bytes()==reply
    finally:proxy.shutdown();proxy.server_close()
    out=state/('outbound-'+mark['id']);result=collect(cards['A']['container'],mark['id'],out)
    assert result['complete_responses']>=1,result
    manifests=list(out.glob('*/response.json'));m=json.loads(manifests[-1].read_text());assert m['sha256']==hashlib.sha256(reply).hexdigest(),m
    req=json.loads((manifests[-1].parent/'request.json').read_text());assert req['complete'];assert req['sha256']==last('A')['input_sha256']
    assert not any(k.lower() in ('authorization','cookie','x-api-key') for k in req['headers'])
    assert not any(k.lower()=='set-cookie' for k in m['headers'])
    assert req['headers'].get('X-Stainless-Os')==['Linux'];assert req['headers'].get('X-Stainless-Arch')==['arm64']
   report['cases'].update(ingress_and_final_transport_sample=True,success_403_stream_bytes_match=True,standard_credentials_not_persisted=True)
   snap=panel('GET','/snapshot')[1];assert snap['summary']['successful_attempts']>=4 and snap['summary']['failed_attempts']>=1,snap['summary']
   assert all(p.get('last_success_at') for p in snap['projects'])
   assert snap['scheduler_in_flight']==0
   for p in snap['projects']:
    for a in p['attempts']:
     assert a['owner']==p['slug'].upper() and a['container']==cards[a['owner']]['container']
     assert any(r['run']==a['run'] and any(t['id']==a['id'] for t in r['attempts']) for r in snap['requests'])
    assert p['usage']['attempt_counts']['confirmed']>=1
    assert p['usage']['totals']['input_tokens']>0 and p['usage']['totals']['output_tokens']>0
   report['cases']['account_request_receipt_usage_join']=True
   report['cases']['shared_usage_request_receipt_summary']=True
   report['captured_headers']={k:v for k,v in req['headers'].items() if k.lower().startswith('x-stainless')}
  except BaseException:
   diagnostic={'error':traceback.format_exc(),'cases':report['cases']}
   if fixture:
    for o in ('A','B'):
     try:(ROOT/'evidence'/('failed-origin-'+o+'.json')).write_text(json.dumps(evidence(o),indent=2))
     except Exception:pass
   for p in (state/'broker-private/environments').glob('*.json'):
    card=json.loads(p.read_text())
    if card.get('container'):
     diagnostic[p.stem]=docker('logs','--tail','15',card['container'])
     check=subprocess.run(CLI+['exec','--user','1001:1001','-i',card['container'],'python3','-B','/opt/sample/worker.py','request'],input='{"op":"open-browser"}',capture_output=True,text=True,timeout=30)
     diagnostic[p.stem+'-browser']={'exit':check.returncode,'stdout':check.stdout,'stderr':check.stderr}
   for name in ['launch','broker','central']:
    p=state/(name+'.log')
    if p.exists():diagnostic[name]=p.read_text()[-3000:]
   (ROOT/'evidence/management-chain-failed.json').write_text(json.dumps(diagnostic,indent=2));raise
  finally:
   (ROOT/'evidence/test-browser-preview.json').unlink(missing_ok=True)
   if process:stop(process)
   for p in (state/'broker-private/environments').glob('*.json'):
    card=json.loads(p.read_text())
    if 'container' not in card:continue
    ident=card['environment_id']
    for listing,remove in [(['ps','-a'],['rm','-f']),(['volume','ls'],['volume','rm'])]:
     ids=docker(*listing,'-q','--filter','label=cpa.retention.id='+ident).split()
     if ids:docker(*remove,*ids)
   if fixture:docker('rm','-f',fixture)
   docker('network','rm',network)
 report['test_resources_removed']=True
 (ROOT/'evidence/management-chain.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':run()

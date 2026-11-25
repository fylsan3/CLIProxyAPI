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
   from request_sample import CaptureServer,Recording,replay,sha
   recorder=Recording(state/'samples','marked-test-request')
   proxy=CaptureServer('http://127.0.0.1:'+str(api.port),recorder)
   threading.Thread(target=proxy.serve_forever,daemon=True).start()
   raw=b'{ "model" : "claude-sonnet-4-6", "max_tokens":16, "messages" : [{"role":"user", "content":"fictional raw replay task"}] }\n'
   try:
    def capture():
     c=http.client.HTTPConnection('127.0.0.1',proxy.server_port,timeout=90)
     try:
      c.request('POST','/v1/messages',raw,{'Authorization':'Bearer '+key,'X-Test-Pin':'a','X-CPA-Sample':'marked-test-request','Content-Type':'application/json'})
      response=c.getresponse();body=response.read();return response.status,body
     finally:c.close()
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
     pending=pool.submit(capture);b=pool.submit(request,'B');status,reply=pending.result();bcode,bbody,bheaders=b.result()
    assert status==200 and bcode==200
    def saved():
     found=list((state/'samples').glob('sample-*/record.json'))
     return found[0].parent if found else None
    sample=wait(saved)
    assert (sample/'request.bin').read_bytes()==raw
    assert (sample/'response.bin').read_bytes()==reply
    assert key not in (sample/'record.json').read_text()
    first=last('A','outbound_capture')
    result=replay(sample,state,state/'replayed')
    second=last('A','outbound_capture')
    assert result['request_body_unchanged'] and result['status']==200
    assert result['historical_response_match'],result
    assert first['body']['messages']==second['body']['messages']
    assert first['body']['messages'][0]['content'][0]['text']==json.loads(raw)['messages'][0]['content']
    report['native_body_transform_observed']={'content':'string converted to text block','cache_control':first['body']['messages'][0]['content'][0].get('cache_control')}
    assert first['body']['max_tokens']==second['body']['max_tokens']==23
    assert all(not any(k.lower().startswith(('x-cpa-','x-offline-')) for k in e['headers']) for e in (first,second))
    assert bheaders['x-test-container']==[cards['B']['container']]
    assert sha(bbody)==last('B')['response_sha256']
    report['cases'].update(raw_capture_and_replay_exact=True,captured_credentials_not_saved=True,actual_A_worker_outbound_compared=True,B_concurrent_request_unaffected=True,internal_marker_not_sent_upstream=True,native_payload_policy_retained=True)
    report['request_sha256']=sha(raw)
    report['input_bytes']=len(raw)
    report['sample_origin']='new fictional client request; not historical WorkBuddy record'
    report['actual_outbound']={'first':first,'replayed':second}
    report['replay']=result
   finally:proxy.shutdown();proxy.server_close()

  except BaseException:
   diagnostic={'error':traceback.format_exc(),'cases':report['cases']}
   if fixture:
    for o in ('A','B'):
     try:(ROOT/'evidence'/('failed-origin-'+o+'.json')).write_text(json.dumps(evidence(o),indent=2))
     except Exception:pass
   for p in (state/'broker-private/environments').glob('*.json'):
    card=json.loads(p.read_text())
    if card.get('container'):diagnostic[p.stem]=docker('logs','--tail','15',card['container'])
   for name in ['launch','broker','central']:
    p=state/(name+'.log')
    if p.exists():diagnostic[name]=p.read_text()[-3000:]
   (ROOT/'evidence/capture-chain-failed.json').write_text(json.dumps(diagnostic,indent=2));raise
  finally:
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
 (ROOT/'evidence/capture-chain.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':run()

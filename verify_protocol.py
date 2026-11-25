"""Exercise the real transport branch against closed HTTPS fixtures, without real accounts."""
import base64,gzip,hashlib,http.client,json,subprocess,tempfile,time,traceback,uuid
from pathlib import Path
from urllib.parse import urlsplit
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
 scope=uuid.uuid4().hex[:12];network='cpa-protocol-'+scope;fixture=None;process=None
 images=json.loads((ROOT/'image.json').read_text());specs=json.loads((ROOT/'tls-fixture/accounts.json').read_text())
 with tempfile.TemporaryDirectory(prefix='cpa-provider-',dir='/tmp') as folder:
  state=Path(folder).resolve();state.chmod(0o700)
  try:
   docker('network','create','--internal','--label','cpa.socks-lab='+scope,network)
   fixture=docker('run','-d','--pull=never','--network',network,'--read-only','--cap-drop','ALL','--tmpfs','/tmp:mode=1777','--tmpfs','/mock:mode=1777',images['tls_fixture'])
   ip=json.loads(docker('inspect',fixture))[0]['NetworkSettings']['Networks'][network]['IPAddress']
   definition=state/'fixture.json';definition.write_text(json.dumps({'mode':'closed_tls_test','scope':scope,'network':network,'ip':ip,'accounts':specs}));definition.chmod(0o600)
   destination=state/'backup-test';destination.mkdir(mode=0o700)
   with (state/'launch.log').open('ab') as log:
    process=subprocess.Popen(['python3','-B',str(ROOT/'launch.py'),'--state',str(state),'--network-fixture',str(definition),'--backup-directory',str(destination),'--max-request-body-bytes','524288'],stdout=log,stderr=log)
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
   catalog=[m['id'] for m in json.loads((ROOT/'models.json').read_text())]
   report['catalog_count']=len(catalog)
   def request(owner='A',content='ordinary',model='claude-sonnet-4-6',path='/v1/messages',stream=False,body=None,compressed=False,chunked=False):
    payload=body or {'model':model,'max_tokens':16,'stream':stream,'messages':[{'role':'user','content':content}]}
    raw=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode()
    headers={'Authorization':'Bearer '+key,'X-Test-Pin':owner.lower(),'Content-Type':'application/json'}
    if compressed:raw=gzip.compress(raw);headers['Content-Encoding']='gzip'
    c=http.client.HTTPConnection('127.0.0.1',api.port,timeout=40)
    try:
     c.request('POST',path,[raw[:100],raw[100:]] if chunked else raw,headers,encode_chunked=chunked)
     response=c.getresponse();result=response.read();return response.status,result,dict(response.getheaders())
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
   # All model IDs come from the native embedded catalog, not handwritten aliases.
   for i,model in enumerate(catalog):
    owner=('A','B')[i%2];check(owner,model=model);assert last(owner)['model']==model
   c=http.client.HTTPConnection('127.0.0.1',api.port,timeout=10)
   c.request('GET','/v1/models',headers={'Authorization':'Bearer '+key});response=c.getresponse();listing=json.loads(response.read());assert response.status==200;c.close()
   assert set(catalog)<={m['id'] for m in listing['data']}
   report['cases']['native_catalog_all_models_routed_and_listed']=True
   check('A',content='x'*196608)
   check('B',content='研'*96000)
   check('A',content='x'*100000,compressed=True)
   check('B',content='x'*100000,chunked=True)
   report['cases']['large_ascii_unicode_gzip_and_chunked_requests']=True
   check('A',model='claude-sonnet-4-6(4096)')
   report['cases']['native_thinking_suffix_routes_without_python_reimplementation']=True
   # Preserve multimodal blocks and tool arguments through the complete bridge.
   png='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aDCkAAAAASUVORK5CYII='
   tool_result='fixture-result-'+'r'*90000
   payload={'model':'claude-sonnet-4-6','max_tokens':16,'messages':[
    {'role':'user','content':[{'type':'image','source':{'type':'base64','media_type':'image/png','data':png}},{'type':'text','text':'inspect fixture'}]},
    {'role':'assistant','content':[{'type':'tool_use','id':'toolu_fixture','name':'read_file','input':{'path':'fixture.txt'}}]},
    {'role':'user','content':[{'type':'tool_result','tool_use_id':'toolu_fixture','content':tool_result}]},
    {'role':'assistant','content':'fixture received'}, {'role':'user','content':'tool_payload'}],
    'tools':[{'name':'read_file','description':'Read a fictional file','input_schema':{'type':'object','properties':{'path':{'type':'string'}},'required':['path']}}]}
   check('A',body=payload);received=last('A');serialized=json.dumps(received['request_messages'])
   assert png in serialized and tool_result in serialized and received['tools'][0]['name']=='read_file'
   tool=check('B',content='tool');assert json.loads(tool)['content'][0]['type']=='tool_use'
   report['cases']['image_large_tool_result_and_tool_use_preserved']=True
   check('A',content='large_reply');check('B',stream=True)
   report['cases']['large_reply_and_stream_byte_exact']=True
   for owner in ('A','B'):
    raw,headers=call(owner,path='/v1/messages/count_tokens',body={'model':'claude-sonnet-4-6','messages':[{'role':'user','content':'count fixture'}]})
    assert json.loads(raw)=={'input_tokens':12345}
    assert hashlib.sha256(raw).hexdigest()==last(owner,'count_tokens')['response_sha256']
    assert headers.get('X-Test-Container')==cards[owner]['container']
   report['cases']['native_upstream_count_tokens_each_account_byte_exact']=True
   pending=http.client.HTTPConnection('127.0.0.1',api.port,timeout=10)
   pending.request('POST','/v1/messages/count_tokens',json.dumps({'model':'claude-sonnet-4-6','messages':[{'role':'user','content':'count_wait'}]}),{'Authorization':'Bearer '+key,'X-Test-Pin':'b','Content-Type':'application/json'})
   wait(lambda:any(e['operation']=='count_started' for e in evidence('B')))
   pending.close()
   wait(lambda:any(e['operation']=='count_cancelled' for e in evidence('B')))
   check('A');report['cases']['count_cancellation_reaches_container_and_other_account_continues']=True
   before=calls()
   for compressed in (False,True):
    code,_,_=request(content='z'*600000,compressed=compressed);assert code==413,code
   assert calls()==before
   report['cases']['native_size_limit_rejects_plain_and_decompressed_overflow_before_upstream']=True
   before=calls();code,_,_=request(model='not-a-catalog-model');assert code>=400;assert calls()==before
   report['cases']['unknown_model_does_not_reach_upstream']=True
   code,raw,_=request('A',content='large_error');assert code==403
   assert hashlib.sha256(raw).hexdigest()==last('A')['response_sha256']
   # Native per-model rejection must not disable unrelated models on the account.
   check('A',model='claude-opus-4-6')
   report['cases']['large_error_byte_exact_and_other_model_still_available']=True
   code,raw,_=request('B',path='/v1/messages/count_tokens',body={'model':'claude-sonnet-4-6','messages':[{'role':'user','content':'count_denied'}]})
   assert code==403 and hashlib.sha256(raw).hexdigest()==last('B','count_tokens')['response_sha256']
   report['cases']['count_error_body_byte_exact']=True
   for owner in ('A','B'):
    records=evidence(owner)
    assert sum(e['operation']=='authorization_code' for e in records)==1
    https=[e for e in records if e['operation']=='https_request']
    assert any(e['path']=='/v1/messages/count_tokens' and e['tls'] for e in https)
    assert not any(h.lower().startswith('x-offline-') or h.lower().startswith('x-test-') for e in https for h in e['header_names'])
   dns=docker('exec',fixture,'python3','-c',"from pathlib import Path;p=Path('/mock/dns.jsonl');print(len(p.read_text().splitlines()) if p.exists() else 0)")
   assert dns=='0'
   report['cases']['single_authorization_no_trace_headers_and_no_dns_queries']=True
  except BaseException:
   diagnostic={'error':traceback.format_exc(),'cases':report['cases']}
   for p in (state/'broker-private/environments').glob('*.json'):
    card=json.loads(p.read_text())
    if card.get('container'):diagnostic[p.stem]=docker('logs','--tail','15',card['container'])
   for name in ['launch','broker','central']:
    p=state/(name+'.log')
    if p.exists():diagnostic[name]=p.read_text()[-3000:]
   (ROOT/'protocol-failed-diagnostic.json').write_text(json.dumps(diagnostic,indent=2));raise
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
 (ROOT/'protocol-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':run()

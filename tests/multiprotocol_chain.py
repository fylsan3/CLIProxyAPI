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
 quota_only="--quota-only" in sys.argv
 cache_only="--cache-only" in sys.argv
 extra_only="--extras-only" in sys.argv or cache_only
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
   cfg=json.loads(cfgpath.read_text());cfg['usage-statistics-enabled']=True;cfg['disable-cooling']=True;cfg['payload']={'override':[{'models':[{'name':'claude-*'}],'params':{'max_tokens':23}}]}
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
   catalog=[m['id'] for m in json.loads((ROOT/'models.json').read_text())];model=catalog[0]
   def request(path,body):
    c=http.client.HTTPConnection('127.0.0.1',api.port,timeout=90)
    try:
     c.request('POST',path,json.dumps(body),{'Authorization':'Bearer '+key,'Content-Type':'application/json'})
     res=c.getresponse();assert not any(k.lower().startswith('x-offline-') for k,v in res.getheaders());return res.status,res.read()
    finally:c.close()
   protocols=[('messages','/v1/messages',{'model':model,'max_tokens':64,'messages':[{'role':'user','content':'hello'}]}),
    ('chat','/v1/chat/completions',{'model':model,'messages':[{'role':'user','content':'hello'}]}),
    ('completions','/v1/completions',{'model':model,'prompt':'hello'}),
    ('responses','/v1/responses',{'model':model,'input':'hello'}),
    ('gemini','/v1beta/models/'+model+':generateContent',{'contents':[{'role':'user','parts':[{'text':'hello'}]}]})]
   if quota_only:
    action('account-update','A')
    code,creds=management('GET','/credentials');a=next(x for x in creds['files'] if x['name']=='a')
    values=a['container_observation']['usage']['values']
    assert values['cedar_ember']['grants'][0]['resets_left']==2
    assert 'must-not-export' not in json.dumps(a)
    assert a['container_capabilities']['reset_grant_read'] and not a['container_capabilities']['reset_grant']
    report['cases']['reset_grants_read_sanitized_no_consume']=True
    docker('exec',fixture,'touch','/mock/A/quota-reset');action('account-update','A')
    for stream in (False,True):
     body={'model':model,'max_tokens':64,'system':[{'type':'text','text':'SYSTEM_KEEP_测试_timezone=UTC'}],'messages':[{'role':'user','content':'MESSAGE_KEEP_测试'}],'stream':stream}
     for owner in ('A','B'):
      arm={'id':uuid.uuid4().hex[:24],'expires':int(time.time())+60,'input_sha256':hashlib.sha256(json.dumps(body).encode()).hexdigest()}
      subprocess.run(CLI+['exec','--user','1001:1001','-i',cards[owner]['container'],'python3','-c',"import sys,os;from pathlib import Path;os.umask(0o077);Path('/state/model-sample-arm.json').write_text(sys.stdin.read())"],input=json.dumps(arm),text=True,check=True)
     code,raw=request('/v1/messages',body);assert code==200,(code,raw[:200])
    seen_system=0
    for owner in ('A','B'):
     rows=[e for e in evidence(owner) if e.get('operation')=='outbound_capture' and e.get('body',{}).get('system')]
     seen_system+=len(rows)
     for row in rows:
      assert 'SYSTEM_KEEP_测试_timezone=UTC' in json.dumps(row['body']['system'],ensure_ascii=False)
      assert 'You are Claude Code' not in json.dumps(row['body']['system'])
      assert 'MESSAGE_KEEP_测试' in json.dumps(row['body']['messages'],ensure_ascii=False)
    assert seen_system==2,seen_system
    report['cases']['system_text_retained_nonstream_and_stream']=True
    report['cases']['newapi_reads_central_only']=True
    docker('exec',fixture,'touch','/mock/A/usage-denied');action('account-update','A');docker('exec',fixture,'rm','/mock/A/usage-denied')
    archive_reports=[]
    for owner in ('A','B'):
     code="""import sys,json;from pathlib import Path
sys.path.insert(0,'/opt/native');import http_archive
root=Path('/state/http-samples');out=[]
if root.exists():
 key=http_archive.private_file(Path('/state/http-capture.key'))
 for sample in root.iterdir():
  manifest=json.loads((sample/'sample.json').read_text())
  for folder in sample.iterdir():
   if not folder.is_dir():continue
   req,res,body,reply=http_archive.load_exchange(folder,key)
   result=http_archive.replay(folder,key)
   headers=http_archive.normalized(http_archive.pairs(req['wire_headers']))
   assert headers.get('authorization') and headers.get('host') and headers.get('user-agent')
   if manifest['kind']=='account-update':
    assert req['method']=='GET' and body==b''
    if '/usage?' in req['url'] and res['status']==200:assert b'must-not-export' in reply and b'cedar_ember' in reply
   out.append({'kind':manifest['kind'],'method':req['method'],'status':res['status'],'request_header_names':sorted(headers),'replay':result})
print(json.dumps(out))
"""
     result=subprocess.run(CLI+['exec','--user','1001:1001','-i',cards[owner]['container'],'python3','-c',code],capture_output=True,text=True,timeout=40)
     assert result.returncode==0,result.stderr[-2000:]
     archive_reports.extend(json.loads(result.stdout))
    assert sum(x['kind']=='account-update' for x in archive_reports)==6,archive_reports
    assert sum(x['kind']=='marked-model-request' for x in archive_reports)==2,archive_reports
    assert any(x['kind']=='account-update' and x['status']==403 for x in archive_reports)
    report['cases']['complete_encrypted_control_and_model_http_replay']=True
    report['archive_replay']=archive_reports

   if not extra_only and not quota_only:
    for owner in ('A','B'):
     for candidate in ('A','B'):assert management('PATCH','/credentials/status',{'name':candidate.lower(),'disabled':candidate!=owner})[0]==200
     for name,path,body in protocols:
      for stream in (False,True):
       current=dict(body,stream=stream);endpoint=path
       if name=='gemini':
        current=dict(body);endpoint=path.replace(':generateContent',':streamGenerateContent?alt=sse') if stream else path
       code,raw=request(endpoint,current)
       assert code==200,(owner,name,stream,code,raw[:600])
       assert (owner+' native OK').encode() in raw,(owner,name,stream,raw[:800])
       assert b'payload' not in raw[:20],raw[:500]
       report['cases'][owner+'_'+name+('_stream' if stream else '')]=True
     rows=[e for e in evidence(owner) if e.get('operation')=='https_request' and e.get('path')=='/v1/messages'];assert rows
     assert all(e['software_headers'].get('X-Stainless-OS')==['Linux'] and e['software_headers'].get('X-Stainless-Arch')==['arm64'] for e in rows),rows[-1]
    for owner in ('A','B'):assert management('PATCH','/credentials/status',{'name':owner.lower(),'disabled':False})[0]==200
    action('account-update','A')
    code,creds=management('GET','/credentials');a=next(x for x in creds['files'] if x['name']=='a')
    assert a['container_observation']['usage']['values']['limits'][0]['percent']==90
    assert 'must-not-export' not in json.dumps(a)
    docker('exec',fixture,'touch','/mock/A/quota-reset');action('account-update','A')
    code,creds=management('GET','/credentials');a=next(x for x in creds['files'] if x['name']=='a');assert a['container_observation']['usage']['values']['limits'][0]['percent']==5
    report['cases']['fable_updated_snapshot_and_private_fields_removed']=True
    action('restart','A');wait(lambda:project('A').get('overall_ready'))
    assert worker('A','/health')[1]['revision']==1
    report['cases']['restart_baseline_and_credentials_preserved']=True
    assert management('PATCH','/credentials/status',{'name':'a','disabled':True,'auth_index':'wrong-binding'})[0]==409
    report['cases']['wrong_binding_rejected']=True
    code,usage=management('GET','/observability/usage/queue?count=100');assert code==200
    assert usage and all(row.get('auth_index') for row in usage),usage
    assert any(row['tokens']['input_tokens']>0 for row in usage),usage
    report['cases']['native_usage_queue_contains_container_account_records']=True
    for owner in ('A','B'):
     observed=project(owner)['usage'];assert observed['attempt_counts']['confirmed']==10,(owner,observed)
    report['cases']['multiprotocol_usage_receipts_confirmed']=True
   if quota_only:
    pass
   elif cache_only:
    for name,path,body in protocols:
     for stream in (False,True):
      body=json.loads(json.dumps(body).replace('hello','cache'));current=dict(body,stream=stream);endpoint=path
      if name=='gemini':current=dict(body);endpoint=path.replace(':generateContent',':streamGenerateContent?alt=sse') if stream else path
      code,raw=request(endpoint,current);assert code==200,(name,stream,code,raw[:500])
      code,rows=management('GET','/observability/usage/queue?count=100');assert code==200 and rows,(name,stream,rows)
      row=rows[-1]['tokens']
      assert (row['input_tokens'],row['output_tokens'],row['cache_creation_tokens'],row['cache_read_tokens'])==(9,3,4,7),(name,stream,row)
      report['cases'][name+('_stream' if stream else '')+'_native_cache_counts']=True
    for owner in ('A','B'):
     observed=project(owner)['usage'];totals=observed['totals'];n=observed['attempt_counts']['confirmed']
     assert totals.get('input_tokens',0)==9*n and totals.get('cache_creation_input_tokens',0)==4*n and totals.get('cache_read_input_tokens',0)==7*n,(owner,observed)
    report['cases']['native_cache_receipts_match_account_totals']=True
   else:
    for name,path in [('chat','/v1/chat/completions'),('responses','/v1/responses')]:
     for prompt in ('tool','denied'):
      body={'model':model,'messages':[{'role':'user','content':prompt}]} if name=='chat' else {'model':model,'input':prompt}
      if prompt=='tool':
       function={'name':'read_file','description':'Read a fixture file','parameters':{'type':'object','properties':{'path':{'type':'string'}},'required':['path']}}
       body['tools']=[{'type':'function','function':function}] if name=='chat' else [dict(type='function',**function)]
      code,raw=request(path,body)
      assert code==(403 if prompt=='denied' else 200),(name,prompt,code,raw[:700])
      assert (b'offline denied' if prompt=='denied' else b'read_file') in raw,(name,prompt,raw[:700])
      report['cases'][name+'_'+prompt+'_preserved']=True
    code,compact=request('/v1/responses/compact',{'model':model,'input':[{'role':'user','content':'hello'}]})
    assert code==200,(code,compact[:500])
    compact=json.loads(compact);assert compact['object']=='response.compaction',compact
    report['cases']['native_responses_compact']=True
    ws_script=ROOT/'evidence/websocket-probe'
    probe=subprocess.run([str(ws_script),'ws://127.0.0.1:'+str(api.port)+'/v1/responses',model],input=key,text=True,capture_output=True,timeout=30)
    assert probe.returncode==0,probe.stdout[-600:]+probe.stderr[-1200:]
    report['cases']['native_responses_websocket']=True
   import os
   newapi=ROOT.parent/'newapi-container-integration'
   tool=ROOT.parent/'cpa-security-audit/lab/replay80/go'
   if newapi.exists() and not extra_only:
    env=dict(os.environ,GOROOT=str(tool),GOMODCACHE=str(ROOT.parent/'newapi-build-cache/modules'),GOCACHE='/tmp/newapi-go-build',GOTOOLCHAIN='local',CPA_AB_TEST_ENDPOINT='http://127.0.0.1:'+str(ui.port),CPA_AB_TEST_KEY=key)
    check=subprocess.run([str(tool/'bin/go'),'test','-p','3','./service','-run','^TestContainerCPAIntegration$','-count=1'],cwd=newapi,env=env,capture_output=True,text=True,timeout=120)
    assert check.returncode==0,check.stdout[-3000:]+check.stderr[-1500:]
    report['cases']['newapi_actual_cpa_management_integration']=True
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
   for name in ['launch','broker','central']:
    p=state/(name+'.log')
    if p.exists():diagnostic[name]=p.read_text()[-3000:]
   (ROOT/'evidence/multiprotocol-chain-failed.json').write_text(json.dumps(diagnostic,indent=2));raise
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
 (ROOT/'evidence'/('quota-browser.json' if quota_only else 'protocol-cache.json' if cache_only else 'protocol-extras.json' if extra_only else 'multiprotocol-chain.json')).write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':run()

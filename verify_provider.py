"""Exercise the real transport branch against closed HTTPS fixtures, without real accounts."""
import base64,hashlib,http.client,json,subprocess,tempfile,time,traceback,uuid
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
 scope=uuid.uuid4().hex[:12];network='cpa-provider-'+scope;fixture=None;process=None
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
    process=subprocess.Popen(['python3','-B',str(ROOT/'launch.py'),'--state',str(state),'--network-fixture',str(definition),'--backup-directory',str(destination)],stdout=log,stderr=log)
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
   report['cases']['https_authorization_token_profile_roles_and_backup_admission']=True
   def model(owner,case='ordinary',stream=False,status=200,model='claude-sonnet-4-5',path='/v1/messages'):
    c=http.client.HTTPConnection('127.0.0.1',api.port,timeout=30)
    try:
     c.request('POST',path,json.dumps({'model':model,'max_tokens':16,'stream':stream,'messages':[{'role':'user','content':case}]}),{'Authorization':'Bearer '+key,'X-Test-Pin':owner.lower(),'Content-Type':'application/json'})
     r=c.getresponse();raw=r.read();assert r.status==status,(case,r.status,raw[:250])
     return raw
    finally:c.close()
   for owner in ('A','B'):
    for case,stream,status in [('ordinary',False,200),('ordinary',True,200)]+([('denied',False,403)] if owner=='A' else []):
     raw=model(owner,case,stream,status)
     event=[e for e in evidence(owner) if e['operation']=='messages'][-1]
     assert event['response_sha256']==hashlib.sha256(raw).hexdigest()
    assert sum(e['operation']=='authorization_code' for e in evidence(owner))==1
   report['cases']['both_accounts_success_and_stream_byte_exact']=True
   report['cases']['a_403_byte_exact']=True
   # A denial may trigger native cooldown; B is used for refresh to exercise
   # the native manager's credential update independently of model cooldown.
   action('auth-refresh','B');wait(lambda:worker('B','/health')[1]['revision']==2)
   wait(lambda:project('B').get('portable_backup',{}).get('revision')==2)
   assert worker('A','/health')[1]['revision']==1
   report['cases']['native_refresh_isolated_and_new_credentials_backed_up']=True
   for owner in ('A','B'):
    records=evidence(owner);https=[e for e in records if e['operation']=='https_request']
    for path in ['/oauth/authorize','/v1/oauth/token','/api/oauth/profile','/api/oauth/claude_cli/roles','/v1/messages']:
     assert any(e['path']==path and e['tls'] for e in https),path
    assert not any(h.lower().startswith('x-offline-') for e in https for h in e['header_names'])
    socks=json.loads(docker('exec',fixture,'python3','-c',"import json;from pathlib import Path;print(json.dumps([json.loads(x) for x in Path('/mock/socks-"+owner+".jsonl').read_text().splitlines()]))"))
    assert all(e['port']==443 and e['remote_domain'] and e['allowed'] and e['proxy']==owner for e in socks)
    report.setdefault('outgoing_summary',{})[owner]=sorted({e['host']+' '+e['method']+' '+e['path'] for e in https})
    browser=json.loads(docker('exec','--user','1001:1001',cards[owner]['container'],'python3','-c',"import json;from pathlib import Path;print(json.dumps(any(b'chromium' in p.read_bytes() for p in Path('/proc').glob('[0-9]*/comm'))))"))
    assert not browser
   report['cases']['official_hosts_tls_remote_dns_and_no_fixture_headers']=True
   report['cases']['browsers_remained_closed']=True
   dns=docker('exec',fixture,'python3','-c',"from pathlib import Path;p=Path('/mock/dns.jsonl');print(len(p.read_text().splitlines()) if p.exists() else 0)")
   assert dns=='0';report['cases']['dns_sensor_zero']=True
   count=sum(e['operation']=='messages' for e in evidence('A'))
   model('A',model='console/unsupported',status=503)
   model('A',path='/v1/messages/count_tokens',status=501)
   assert sum(e['operation']=='messages' for e in evidence('A'))==count
   report['cases']['unsupported_paths_fail_locally_without_provider_calls']=True
   # Stop only A's SOCKS fixture. Even a direct worker invocation must not
   # bypass the bound proxy; the healthy B account must continue normally.
   before={o:sum(e['operation']=='messages' for e in evidence(o)) for o in ('A','B')}
   docker('exec',fixture,'python3','-c',"import os,signal;from pathlib import Path;os.kill(int(Path('/mock/proxy-A.pid').read_text()),signal.SIGTERM)")
   code,_=worker('A','/v1/messages',{'model':'claude-sonnet-4-5','max_tokens':16,'messages':[{'role':'user','content':'ordinary'}]})
   assert code>=400
   model('A',status=503)
   assert all(sum(e['operation']=='messages' for e in evidence(o))==before[o] for o in ('A','B'))
   raw=model('B',stream=True)
   assert [e for e in evidence('B') if e['operation']=='messages'][-1]['response_sha256']==hashlib.sha256(raw).hexdigest()
   report['cases']['a_proxy_down_no_direct_or_b_fallback_b_stream_continues']=True
   raw=model('B',case='denied',status=403)
   assert [e for e in evidence('B') if e['operation']=='messages'][-1]['response_sha256']==hashlib.sha256(raw).hexdigest()
   report['cases']['b_403_byte_exact']=True
   ordinary=docker('run','--rm','--network','none','--entrypoint','python3',images['id'],'-c',"from pathlib import Path;print(Path('/usr/local/share/ca-certificates/cpa-local-test.crt').exists())")
   assert ordinary=='False';report['cases']['ordinary_image_has_no_test_ca']=True
  except BaseException:
   diagnostic={'error':traceback.format_exc(),'cases':report['cases']}
   for p in (state/'broker-private/environments').glob('*.json'):
    card=json.loads(p.read_text())
    if card.get('container'):diagnostic[p.stem]=docker('logs','--tail','15',card['container'])
   for name in ['launch','broker','central']:
    p=state/(name+'.log')
    if p.exists():diagnostic[name]=p.read_text()[-3000:]
   (ROOT/'provider-failed-diagnostic.json').write_text(json.dumps(diagnostic,indent=2));raise
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
 (ROOT/'provider-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))

if __name__=='__main__':run()

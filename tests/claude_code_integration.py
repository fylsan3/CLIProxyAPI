"""Real pinned CLI + real central API + fake A/B, network-none containers."""
import contextlib,http.client,io,json,os,socket,socketserver,subprocess,sys,tarfile,tempfile,threading,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from host_runtime import docker_cli,docker_socket
from central_policy import mac_profile
from maintenance import MaintenanceGate
from claude_code_control import command,action
from broker import Handler
CLI=docker_cli();OUT=ROOT/'evidence/claude-code-build';OUT.mkdir(exist_ok=True)
def docker(*args):return subprocess.check_output(CLI+list(args),text=True,stderr=subprocess.STDOUT).strip()
def wait(fn,seconds=30):
 until=time.monotonic()+seconds;last=None
 while time.monotonic()<until:
  try:
   value=fn()
   if value:return value
  except (OSError,ValueError,subprocess.SubprocessError) as e:last=str(e)
  time.sleep(.2)
 raise RuntimeError('fixture wait failed: '+str(last))
def request_http(port,path,body=None,key=None):
 c=http.client.HTTPConnection('127.0.0.1',port,timeout=100)
 try:
  headers={'Content-Type':'application/json'}
  if key:headers['Authorization']='Bearer '+key
  c.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,headers);r=c.getresponse();data=r.read()
  return r.status,json.loads(data) if data else {}
 finally:c.close()
class Registry:
 def get(self,slug):
  if slug not in ('a','b'):raise ValueError('unknown_account')
  return {'owner':slug.upper(),'slug':slug,'provider':'mock-claude'}
class FixtureBroker:
 def __init__(self,containers):self.registry=Registry();self.gate=MaintenanceGate();self.containers=containers
 def inspect(self,owner):return json.loads(docker('inspect',self.containers[owner]))[0]
 def admin(self,op,body,connection=None):
  if op=='ui-action':return action(self,body)
  if op=='dashboard':
   return 200,{'projects':[{'slug':x.lower(),'label':'Fictional '+x,'container':c,'reason':'authorization_required','overall_ready':False,'protection':{'phase':'awaiting_authorization'},'state':{},'network':{'healthy':True},'attempts':[],'usage':None,'statistics':None,'portable_backup':{},'central_dispatch':{'reason':'unknown'}} for x,c in self.containers.items()], 'requests':[],'summary':{'last_success':{}},'runtime_mode':'test','available_providers':{'mock-claude':{'label':'Offline'}},'logging_to_file':False,'release':{'candidate':'claude-code-2.1.331-test'}}
  return 200,{}
class Unix(socketserver.ThreadingMixIn,socketserver.UnixStreamServer):daemon_threads=True

def main():
 suffix=uuid.uuid4().hex[:8];image='cpa-claude-fixture:'+suffix;containers={};volumes=[];central=None;server=None;report={'real_accounts_used':False,'production_changed':False,'cases':{}}
 manifest=json.loads((OUT/'manifest.json').read_text())
 report['image_id']=manifest['image_id'];report['claude_version']=manifest['claude']['version']
 cert=OUT/'test-ca.crt';certkey=OUT/'test-ca.key'
 subprocess.run(['/usr/bin/openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','2','-keyout',str(certkey),'-out',str(cert),'-subj','/CN=CPA closed test only','-addext','subjectAltName=DNS:api.anthropic.com,DNS:claude.ai,DNS:platform.claude.com'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 certkey.chmod(0o600)
 p=subprocess.Popen(CLI+['build','--network','none','--pull=false','-q','-t',image,'-'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=(OUT/'fixture-build.log').open('wb'))
 with tarfile.open(fileobj=p.stdin,mode='w|') as t:
  data=('FROM '+manifest['image_id']+'\nCOPY fixture.py lifecycle_test.py test-ca.crt test-ca.key /bench/\n').encode();i=tarfile.TarInfo('Dockerfile');i.size=len(data);t.addfile(i,io.BytesIO(data));t.add(ROOT/'tests/claude_code_fixture.py',arcname='fixture.py');t.add(ROOT/'tests/claude_lifecycle_test.py',arcname='lifecycle_test.py');t.add(cert,arcname='test-ca.crt');t.add(certkey,arcname='test-ca.key')
 p.stdin.close();p.stdout.read();assert p.wait()==0
 with tempfile.TemporaryDirectory(prefix='cpa-claude-test-',dir='/tmp') as temp:
  state=Path(temp);sock=state/'bridge.sock'
  try:
   for owner in ('A','B'):
    volume='cpa-claude-'+suffix+'-'+owner.lower();docker('volume','create',volume);volumes.append(volume)
    args=['run','-d','--name',volume,'--user','0:0','--network','none','--read-only','--memory','1g','--memory-swap','1g','--cpus','2','--pids-limit','256','--security-opt','seccomp='+str(ROOT/'security/seccomp.json'),'--cap-drop','ALL']
    for cap in ('SETUID','SETGID','CHOWN','FOWNER','DAC_OVERRIDE','KILL'):args+=['--cap-add',cap]
    args+=['--tmpfs','/tmp:rw,exec,mode=1777,size=128m','--tmpfs','/run/network:rw,size=1m','--mount','type=volume,source='+volume+',target=/state','-e','FIXTURE_OWNER='+owner,'-e','CPA_PROVIDER=mock-claude','--entrypoint','python3',image,'-B','/bench/fixture.py']
    containers[owner]=docker(*args)
   broker=FixtureBroker(containers)
   for slug in ('a','b'):wait(lambda:command(broker,slug,'status',{})[0]==200)
   def cli_pids(slug):
    script="import os,json;from pathlib import Path;found=[]\nfor p in Path('/proc').glob('[0-9]*/exe'):\n try:\n  if os.readlink(p)=='/opt/claude-code/claude':found.append(int(p.parent.name))\n except OSError:pass\nprint(json.dumps(found))"
    return json.loads(docker('exec','--user','1001:1001',containers[slug.upper()],'python3','-c',script))
   def idle(slug):
    return command(broker,slug,'status',{})[1].get('state')=='idle' and not cli_pids(slug)
   for slug in ('a','b'):
    assert idle(slug)
    assert docker('exec',containers[slug.upper()],'python3','-c',"from pathlib import Path;print(Path('/tmp/auth-observations.jsonl').exists())")=='False'
   report['cases']['boot_and_status_no_CLI_no_model_requests']=True
   unit=docker('exec','--user','1001:1001',containers['A'],'python3','-B','/bench/lifecycle_test.py')
   (OUT/'lifecycle-unit-test.log').write_text(unit)
   report['cases']['eight_injected_lifecycle_fault_checks']=True
   server=Unix(str(sock),Handler);server.broker=broker;threading.Thread(target=server.serve_forever,daemon=True).start()
   with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
   key='fixture-'+uuid.uuid4().hex;cfg={'host':'127.0.0.1','port':port,'auth-dir':str(state/'auth'),'api-keys':[key],'remote-management':{'secret-key':key},'request-log':False}
   (state/'auth').mkdir();config=state/'config.json';config.write_text(json.dumps(cfg))
   env={'PATH':'/usr/bin:/bin','HOME':str(state),'TMPDIR':str(state),'CPA_CONTAINER_SOCKET':str(sock),'MANAGEMENT_STATIC_PATH':str(ROOT/'static')}
   central=subprocess.Popen(['/usr/bin/sandbox-exec','-p',mac_profile([sock],[],docker_socket(),inbound_port=port),str(OUT/'central-darwin'),'-config',str(config),'-local-model'],env=env,cwd=state,stdout=(OUT/'central-test.log').open('wb'),stderr=subprocess.STDOUT)
   wait(lambda:request_http(port,'/healthz')[0]==200)
   payload={'account':'a','prompt':'Please only reply OK','model':'claude-sonnet-4-6'}
   assert request_http(port,'/v1/claude-code/messages',payload)[0]==401;report['cases']['api_requires_key']=True
   for slug in ('a','b'):
    code,data=request_http(port,'/v1/claude-code/messages',dict(payload,account=slug),key)
    assert code==200 and data['result']['result']=='OK',(code,data)
    assert data['container']==containers[slug.upper()][:12] and data['account']==slug
    assert idle(slug)
    report['cases'][slug+'_api_OK_correct_container_and_process_exited']=True
   assert command(broker,'a','job-start',{'prompt':'x','command':'sh'})[0]==400
   assert request_http(port,'/v1/claude-code/messages',dict(payload,account='../a'),key)[0]==400
   report['cases']['reject_command_and_bad_account']=True
   code,t=command(broker,'a','terminal-start',{'mode':'interactive','cols':100,'rows':27});assert code==200,t
   wait(lambda:bool(command(broker,'a','terminal-read',{'id':t['id'],'offset':0})[1].get('data')))
   import base64
   code,reply=command(broker,'a','terminal-input',{'id':t['id'],'data':base64.b64encode(b'\r').decode()})
   output=command(broker,'a','terminal-read',{'id':t['id'],'offset':0})[1]
   (OUT/'terminal-initial.txt').write_bytes(base64.b64decode(output.get('data','')))
   assert code==200,reply
   assert command(broker,'a','terminal-resize',{'id':t['id'],'cols':90,'rows':25})[0]==200
   assert command(broker,'a','job-start',{'prompt':'x'})[0]==409
   assert command(broker,'b','terminal-read',{'id':t['id'],'offset':0})[0]==409
   assert command(broker,'a','terminal-stop',{'id':t['id']})[0]==200
   report['cases']['real_CLI_PTY_input_resize_stop_and_isolation']=True
   assert command(broker,'a','terminal-start',{'mode':'login'})[1]['error']=='use_go_authorization'
   report['cases']['separate_CLI_login_disabled']=True
   def rotate(slug,revision,seconds=14400):
    script="import json,os,time;from pathlib import Path;from datetime import datetime,timezone;p=Path('/state/native-auth.json');v=json.loads(p.read_text());v['revision']=REV;v['token']['access_token']='sk-ant-oat01-offline-'+v['owner']+'-'+str(REV);v['token']['expired']=datetime.fromtimestamp(time.time()+SECONDS,timezone.utc).isoformat();q=p.with_suffix('.new');q.write_text(json.dumps(v));q.chmod(0o600);os.replace(q,p)"
    docker('exec','--user','1001:1001',containers[slug.upper()],'python3','-c',script.replace('REV',str(revision)).replace('SECONDS',str(seconds)))
   rotate('a',2)
   code,result=request_http(port,'/v1/claude-code/messages',payload,key)
   assert code==200 and result['credential_revision']==2 and result['result']['result']=='OK',result
   observations=[json.loads(line) for line in docker('exec',containers['A'],'cat','/tmp/auth-observations.jsonl').splitlines()]
   assert all(x['authorization_matches_go'] for x in observations),observations
   assert observations[-1]['revision']==2
   assert not any('oauth/token' in x['path'] for x in observations)
   status=command(broker,'a','status',{})[1]
   assert status['authentication']['refresh_owner']=='go' and 'sk-ant' not in json.dumps(status)
   report['cases']['real_CLI_uses_Go_token_and_new_revision_no_refresh']=True
   rotate('a',3,-1)
   assert command(broker,'a','job-start',{'prompt':'x'})[1]['error']=='waiting_for_go_refresh'
   assert command(broker,'b','status',{})[1]['authentication']['ready']
   rotate('a',4)
   assert command(broker,'a','status',{})[1]['authentication']['revision']==4
   report['cases']['expired_access_waits_for_Go_B_unaffected']=True
   code,job=command(broker,'a','job-start',{'prompt':'Please only reply OK','model':'claude-sonnet-4-6'});assert code==200,job
   assert command(broker,'a','job-cancel',{'id':job['id']})[0]==200
   wait(lambda:command(broker,'a','job-read',{'id':job['id']})[1]['state']=='cancelled')
   report['cases']['job_cancellation']=True
   assert idle('a')
   # Delay only this local fixture response, making cancellation/crash deterministic.
   docker('exec',containers['A'],'sh','-c','echo 20 > /tmp/model-delay')
   auth_hash=docker('exec',containers['A'],'sha256sum','/state/native-auth.json')
   connection=socket.create_connection(('127.0.0.1',port));body=json.dumps(payload).encode()
   connection.sendall(('POST /v1/claude-code/messages HTTP/1.1\r\nHost: localhost\r\nAuthorization: Bearer '+key+'\r\nContent-Type: application/json\r\nContent-Length: '+str(len(body))+'\r\n\r\n').encode()+body)
   wait(lambda:cli_pids('a'));connection.close();wait(lambda:idle('a'))
   report['cases']['client_disconnect_cancels_and_cleans']=True
   code,job=command(broker,'a','job-start',{'prompt':'offline crash fixture','model':'claude-sonnet-4-6'});assert code==200
   pids=wait(lambda:cli_pids('a'))
   docker('exec',containers['A'],'kill','-KILL',str(pids[0]))
   wait(lambda:command(broker,'a','job-read',{'id':job['id']})[1]['state']=='failed');assert idle('a')
   code,data=request_http(port,'/v1/claude-code/messages',dict(payload,account='b'),key);assert code==200 and data['result']['result']=='OK'
   report['cases']['CLI_crash_cleanup_B_completes']=True
   assert docker('exec',containers['A'],'sha256sum','/state/native-auth.json')==auth_hash
   report['cases']['cancel_and_crash_do_not_rewrite_Go_credentials']=True
   # Persist an innocuous marker, restart the whole container, confirm no loss/cross-account reuse.
   docker('exec','--user','1001:1001',containers['A'],'python3','-c',"from pathlib import Path;Path('/state/claude-code/home/test-marker').write_text('A')")
   code,interrupted=command(broker,'a','job-start',{'prompt':'restart while running','model':'claude-sonnet-4-6'});assert code==200
   wait(lambda:cli_pids('a'));docker('restart',containers['A']);wait(lambda:command(broker,'a','status',{})[0]==200)
   assert idle('a') and command(broker,'a','job-read',{'id':interrupted['id']})[1]['error']=='job_not_found'
   assert docker('exec',containers['A'],'sha256sum','/state/native-auth.json')==auth_hash
   assert docker('exec',containers['A'],'python3','-c',"from pathlib import Path;print(Path('/tmp/auth-observations.jsonl').exists())")=='False'
   code,data=request_http(port,'/v1/claude-code/messages',payload,key)
   assert code==200 and data['result']['result']=='OK' and data['credential_revision']==4 and idle('a')
   report['cases']['restart_inflight_no_replay_no_CLI_until_next_request']=True
   assert docker('exec',containers['A'],'cat','/state/claude-code/home/test-marker')=='A'
   assert docker('exec',containers['B'],'python3','-c',"from pathlib import Path;print(Path('/state/claude-code/home/test-marker').exists())")=='False'
   report['cases']['container_restart_persistent_home_account_isolation']=True
   docker('exec',containers['A'],'touch','/tmp/proxy-failed');time.sleep(.4)
   assert command(broker,'a','job-start',{'prompt':'x'})[0]==409
   assert command(broker,'b','status',{})[0]==200;report['cases']['network_gate_fail_closed_B_unaffected']=True
   docker('exec',containers['A'],'rm','/tmp/proxy-failed');time.sleep(.4)
   (OUT/'ui-test-input.json').write_text(json.dumps({'url':'http://127.0.0.1:'+str(port)+'/management.html','key':key}))
   ui=ROOT/'tests/claude_code_ui.cjs'
   module=os.environ.get('CPA_PLAYWRIGHT_MODULE')
   if module and ui.exists():
    result=subprocess.run(['/opt/homebrew/bin/node',str(ui)],input=(OUT/'ui-test-input.json').read_text(),text=True,capture_output=True,env=os.environ,timeout=75)
    (OUT/'ui-test.log').write_text(result.stdout+result.stderr);assert result.returncode==0,result.stderr[-1500:];report['cases']['management_terminal_UI']=True
   else:report['cases']['management_terminal_UI']='not_run'
   assert idle('a') and idle('b')
   report['cases']['all_cases_leave_no_CLI_processes']=True
   report['passed']=True
   report['container_security_policy']='security/seccomp.json'
  finally:
   if central and central.poll() is None:central.terminate();central.wait(timeout=10)
   if server:server.shutdown();server.server_close()
   for c in containers.values():
    try:(OUT/(c[:12]+'-fixture.log')).write_text(docker('logs',c))
    except subprocess.SubprocessError:pass
    try:docker('rm','-f',c)
    except subprocess.SubprocessError:pass
   for v in volumes:
    try:docker('volume','rm',v)
    except subprocess.SubprocessError:pass
   docker('image','rm',image)
   certkey.unlink(missing_ok=True);cert.unlink(missing_ok=True)
   (OUT/'ui-test-input.json').unlink(missing_ok=True)
   (OUT/'test-report.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
if __name__=='__main__':main()

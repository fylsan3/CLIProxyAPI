"""Added-network regression, strictly called with disposable A/B fixture resources."""
import json,subprocess,time
from lab_support import CLI,docker

def exercise(report,cards,specs,fixture,worker,browser,action,management,request,project,evidence,model,wait):
 cases=report['cases']
 def run(owner,script,uid='1001:1001'):
  p=subprocess.run(CLI+['exec','--user',uid,cards[owner]['container'],'python3','-B','-c',script],capture_output=True,text=True,timeout=15)
  assert p.returncode==0,p.stderr[-1500:]
  return json.loads(p.stdout or '{}')
 def select(owner):
  for other in ('A','B'):assert management('PATCH','/credentials/status',{'name':other.lower(),'disabled':other!=owner})[0]==200
 def task(owner,stream=False,content='hello'):
  select(owner);code,raw=request('/v1/messages',{'model':model,'max_tokens':64,'stream':stream,'system':'KEEP_SYSTEM_timezone=UTC','messages':[{'role':'user','content':content}]})
  assert code==200 and (owner+' native OK').encode() in raw,(owner,code,raw[:500]);return raw
 for owner in ('A','B'):
  cid=cards[owner]['container'];info=json.loads(docker('inspect',cid))[0]
  assert info['HostConfig']['Memory']==2*1024**3
  state=run(owner,"from pathlib import Path;import json;print(Path('/run/network/live/status.json').read_text())")
  assert state['healthy'] and state['egress_manager']=='go' and state['timezone_check_reason']=='timezone_verified',state
  assert state['periodic_network_checks'] is False
  health=worker(owner,'/health')[1];assert health['egress_policy']=='account-egress-3-usage-headers' and health['resources']['memory_limit_bytes']==2*1024**3
  assert not browser(owner,{'op':'status'})['browser']
  process=run(owner,"""from pathlib import Path
import json
out=[]
for p in Path('/proc').glob('[0-9]*/cmdline'):
 try:
  a=p.read_bytes().split(b'\0')
  if a[:2]==[b'/opt/native/worker',b'network-serve']:out.append({'pid':int(p.parent.name),'uid':p.parent.stat().st_uid})
 except OSError:pass
print(json.dumps(out))""")
  assert len(process)==1 and process[0]['uid']==1002,process
  assert run(owner,"from pathlib import Path;import json;print(json.dumps({'legacy_adapter':Path('/opt/native/socks_adapter.py').exists()}))")['legacy_adapter'] is False
  run(owner,"from pathlib import Path\ntry:Path('/state/native-auth.json').read_bytes()\nexcept PermissionError:print('{}')\nelse:raise AssertionError('network process can read credential')",'1002:1002')
  peer=json.loads(docker('inspect',fixture))[0]['NetworkSettings']['Networks'][cards[owner]['network']]['IPAddress']
  # TCP peer, alternate direct service and Docker embedded DNS: all denied for account user.
  checks=run(owner,"""import socket,json
out={}
for name,addr in [('proxy',(%r,%d)),('direct',(%r,%d)),('dns',('127.0.0.11',53))]:
 try:s=socket.create_connection(addr,timeout=.6);s.close();out[name]=False
 except OSError:out[name]=True
print(json.dumps(out))"""%(peer,specs[owner]['proxy_port'],peer,specs[owner]['origin_port']))
  assert all(checks.values()),checks
  rules=docker('exec',cid,'iptables-nft','-S','OUTPUT')
  assert '--uid-owner 1002' in rules and '--dport 53 -j DROP' in rules
  before=health['revision'];assert worker(owner,'/auth/refresh')[0]==200
  assert worker(owner,'/health')[1]['revision']==before+1
  action('account-update',owner);task(owner);task(owner,True)
  rows=[e for e in evidence(owner) if e.get('operation')=='https_request'];report[owner+'_outbound_observations']=rows
  for path in ('/v1/oauth/token','/api/oauth/profile','/api/oauth/claude_cli/roles','/api/oauth/usage','/v1/messages'):
   found=[e for e in rows if e['path']==path];assert found,(owner,path)
   expected='claude-cli/2.1.331 (external, sdk-cli)' if path=='/v1/messages' else 'axios/1.15.2'
   assert all(e['software_headers']['User-Agent']==[expected] for e in found),(path,found)
  assert any(e['host']=='ipwho.is' and e['software_headers']['User-Agent']==['CPA-Network-Check/1'] for e in rows)
  assert any(e['path']=='/oauth/authorize' and any('Chrome/' in v for v in e['software_headers']['User-Agent']) for e in rows)
  wire=json.loads(docker('exec',fixture,'python3','-c',"from pathlib import Path;import json;print(json.dumps([json.loads(x) for x in Path('/mock/socks-"+owner+".jsonl').read_text().splitlines()]))"))
  assert all(x['remote_domain'] and x['proxy']==owner for x in wire)
  cases[owner+'_go_only_egress_uid_and_no_direct_or_dns']=True
  cases[owner+'_browser_oauth_profile_usage_refresh_model_stream']=True
  cases[owner+'_header_policy_observed_and_browser_closed']=True
 # Reject A's peer while B continues. Close existing idle connections by fresh requests.
 a=cards['A']['container'];port=str(specs['A']['proxy_port'])
 rule=['-p','tcp','--dport',port,'-j','REJECT']
 docker('exec',a,'iptables-nft','-I','OUTPUT','1',*rule)
 try:
  assert worker('A','/auth/account-update')[0]!=200
  task('B',True)
  before=len([e for e in evidence('A') if e.get('operation')=='messages'])
  select('A');code,raw=request('/v1/messages',{'model':model,'max_tokens':64,'messages':[{'role':'user','content':'blocked-network'}]})
  assert code!=200,(code,raw[:100])
  assert len([e for e in evidence('A') if e.get('operation')=='messages'])==before
  # On reboot a failed initial check must leave credentials unopened.
  docker('restart',a)
  # iptables is rebuilt on restart, so this verifies restart recovery, not persistent outage.
  wait(lambda:worker('A','/health')[0]==200)
 finally:
  # Restart removed the test rule. Remove only if a failed assertion prevented restart.
  subprocess.run(CLI+['exec',a,'iptables-nft','-D','OUTPUT',*rule],capture_output=True)
 action('retry-backup','A');wait(lambda:project('A').get('overall_ready'));task('A')
 cases['A_proxy_failure_no_upstream_call_B_stream_unaffected_then_restart']=True
 # Stop only A's Go network process. Its supervisor must terminate the whole executor.
 run('A',"""from pathlib import Path
import os,signal,json
for p in Path('/proc').glob('[0-9]*/cmdline'):
 try:
  if p.read_bytes().split(b'\0')[:2]==[b'/opt/native/worker',b'network-serve']:os.kill(int(p.parent.name),signal.SIGTERM)
 except OSError:pass
print('{}')""",'0:0')
 wait(lambda:not json.loads(docker('inspect',a))[0]['State']['Running'])
 task('B',True)
 cases['A_go_network_exit_stops_executor_B_stream_unaffected']=True
 action('restart','A');wait(lambda:project('A').get('overall_ready'));task('A')
 cases['A_restart_preserves_refreshed_credentials_and_environment']=True
 report['browser_interaction_tested']='actual Chromium loaded fixture authorization page; fixture callback completed locally; no human verification'

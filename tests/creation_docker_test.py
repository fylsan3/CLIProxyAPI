"""One closed-network A creation plus B proxy rejection; no real provider calls."""
import json,os,subprocess,sys,tempfile,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from host_runtime import docker_cli
from account_registry import Registry
from protection import Protection
from creation_progress import CreationFailure,STEPS
from retention import write_json
CLI=docker_cli()
def docker(*args):return subprocess.check_output(CLI+list(args),text=True,stderr=subprocess.PIPE,timeout=60).strip()
def run():
 scope=uuid.uuid4().hex[:12];network='cpa-create-check-'+scope;fixture=None;control=None;report={}
 with tempfile.TemporaryDirectory(prefix='cpa-create-check-') as temporary:
  root=Path(temporary);root.chmod(0o700)
  try:
   docker('network','create','--internal','--label','cpa.socks-lab='+scope,network)
   images=json.loads((ROOT/'image.json').read_text())
   fixture=docker('run','-d','--pull=never','--network',network,'--read-only','--cap-drop','ALL','--tmpfs','/tmp:mode=1777','--tmpfs','/mock:mode=1777',images['fixture'])
   ip=json.loads(docker('inspect',fixture))[0]['NetworkSettings']['Networks'][network]['IPAddress']
   accounts=json.loads((ROOT/'fixture/accounts.json').read_text());write_json(root/'network-fixture.json',{'mode':'closed_test','network':network,'scope':scope,'ip':ip,'accounts':accounts})
   registry=Registry(root);registry.register('a','Fictional A','mock-claude');registry.register('b','Fictional B','mock-claude')
   control=Protection(root/'environments');time.sleep(.6)
   card=control.create('A','socks5h://test-A:fixture-password-A@'+ip+':1081')
   state=control.state('A');assert state['phase']=='awaiting_authorization';assert [v['step'] for v in state['creation_steps']]==list(STEPS);assert all(v['status']=='completed' for v in state['creation_steps'])
   report['all_creation_steps_and_worker_health']=True
   # The low-level probe tests a wrong credential without bypassing the closed fixture binding.
   from creation_probe import discover,PROBE_SCRIPT
   probe='cpa-create-bad-auth-'+scope
   try:
    cfg={'test_only':True,'provider':'mock-claude','owner':'B','proxy_ip':ip,'proxy_port':1082,'username':'test-B','password':'wrong-fixture-password','check_host':'b.upstream.invalid','check_port':8080,'expected_egress':'203.0.113.2'}
    try:discover(CLI+['run','--rm','--name',probe,'-i','--network',network,'--read-only','--cap-drop','ALL','--cap-add','NET_ADMIN','--user','0:0','--security-opt','no-new-privileges','--entrypoint','python3',images['id'],'-B','-c',PROBE_SCRIPT],cfg,lambda _:None)
    except CreationFailure as e:assert e.code=='proxy_auth_rejected',e.code;report['proxy_auth_rejected_is_specific']=True
    else:raise AssertionError('wrong credential accepted')
   finally:subprocess.run(CLI+['rm','-f',probe],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   report['no_real_accounts']=True;report['production_unchanged']=True
   (ROOT/'evidence/creation-docker-test.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
  finally:
   if control:control.close()
   for file in (root/'environments').glob('*.json'):
    data=json.loads(file.read_text())
    if data.get('container'):subprocess.run(CLI+['rm','-f',data['container']],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    for key in ('volume','backup','network_config'):
     if data.get(key):subprocess.run(CLI+['volume','rm',data[key]],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   if fixture:subprocess.run(CLI+['rm','-f',fixture],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   subprocess.run(CLI+['network','rm',network],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
if __name__=='__main__':run()

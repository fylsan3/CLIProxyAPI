"""Exercise launchd cutover/rollback with fake keys and zero real accounts."""
import hashlib,http.client,json,os,plistlib,secrets,shutil,socket,subprocess,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT))
from mac_release import Switch,make_plist,prepare_state,verify_new,wait_for,request,write_json,copy_release,local_ipv4
from central_policy import mac_profile
from host_runtime import docker_cli,docker_socket
from version import release_info

def run():
 report={'real_accounts_used':False,'production_services_changed':False,'cases':{}};scope=secrets.token_hex(8);network='cpa-release-test-'+scope
 cli=docker_cli();label='com.local.cpa-release-test.'+scope;job='gui/'+str(os.getuid())+'/'+label
 subprocess.run(cli+['network','create','--label','cpa.account-network='+scope,network],check=True,stdout=subprocess.DEVNULL)
 with tempfile.TemporaryDirectory(prefix='cpa-mac-release-',dir='/tmp') as tmp:
  root=Path(tmp).resolve();root.chmod(0o700);key='fictional-management-password';client_a=secrets.token_hex(24);client_b=secrets.token_hex(24)
  with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
  old=root/'old';old.mkdir(mode=0o700);(old/'auth-empty').mkdir(mode=0o700)
  cfg={'config-version':8,'server':{'host':'','port':port,'tls':{'enable':False},'discovery':{'enabled':False}},'management':{'secret-key':key,'allow-remote':False,'disable-auto-update-panel':True},'access':{'api-keys':[client_a,client_b]},'oauth':{'auth-dir':str(old/'auth-empty')},'observability':{'logs':{'logging-to-file':True,'request-log':False}},'routing':{'retry':{'request-retry':3}}}
  write_json(old/'config.yaml',cfg)
  previous=old/'cli-proxy-api';shutil.copy2(Path.home()/'cliproxyapi/bin/cli-proxy-api',previous)
  plist=root/'service.plist';state=root/'state';backup=root/'backup';networkfile=root/'network.json'
  write_json(networkfile,{'mode':'managed','scope':scope,'network':network})
  original={'Label':label,'ProgramArguments':['/usr/bin/sandbox-exec','-p',mac_profile([root/'unused.sock'],[Path.home()/'.cli-proxy-api',Path.home()/'cliproxyapi'],docker_socket()),str(previous),'-config',str(old/'config.yaml'),'-local-model'],'WorkingDirectory':str(old),'RunAtLoad':True,'KeepAlive':True,'StandardOutPath':str(old/'out.log'),'StandardErrorPath':str(old/'err.log')}
  plist.write_bytes(plistlib.dumps(original));plist.chmod(0o600)
  def old_ok():return request(port,'/healthz')[0]==200 and request(port,'/v8/management/credentials',key)[0]==200
  try:
   subprocess.run(['launchctl','bootstrap','gui/'+str(os.getuid()),str(plist)],check=True)
   wait_for(old_ok)
   result=prepare_state(old/'config.yaml',state,key,backup)
   assert result['configuration_preserved_except_auth_directory'] and result['api_key_count']==2
   cfg_hash=hashlib.sha256((state/'config.yaml').read_bytes()).hexdigest()
   release=root/'release';copy_release(ROOT,release)
   new=make_plist(label,release,state,networkfile,backup)
   switch=Switch(plist,root/'successful-switch',port)
   switch.apply(new,lambda:verify_new(state,key,release_info()['candidate']),old_ok)
   report['cases']['actual_launchd_switch_to_new_central_and_broker']=True
   for token in (client_a,client_b):assert request(port,'/v1/models',token)[0]==200
   assert request(port,'/v1/models')[0]==401
   assert request(port,'/v8/management/credentials',key)[0]==200
   report['cases']['existing_multiple_api_keys_and_management_password_preserved']=True
   status,raw=request(port,'/v1/messages',client_a,'POST',{'model':'claude-sonnet-4-6','max_tokens':1,'messages':[{'role':'user','content':'offline no-account check'}]})
   assert status in (400,404,503),(status,raw[:100]);report['empty_account_status']=status
   report['cases']['no_account_request_fails_without_host_fallback']=True
   page=request(port,'/accounts.html')[1];assert len(page)>10000
   report['cases']['integrated_management_page_available']=True
   addresses=local_ipv4();ip=addresses[0] if addresses else ''
   if ip:
    c=http.client.HTTPConnection(ip,port,timeout=5);c.request('GET','/v1/models',headers={'Authorization':'Bearer '+client_a});res=c.getresponse();res.read();assert res.status==200;c.close();report['cases']['non_loopback_api_listener_preserved']=True
   else:report['lan_listener_test']='no en0 IPv4 address available'
   # The same production profile must reject an outbound TCP connection.
   with socket.socket() as listener:
    listener.bind(('127.0.0.1',0));listener.listen(1)
    script='import socket,errno; s=socket.socket(); code=s.connect_ex(("127.0.0.1",'+str(listener.getsockname()[1])+')); assert code in (errno.EPERM,errno.EACCES),code'
    subprocess.run(['/usr/bin/sandbox-exec','-p',mac_profile([state/'.test-projects.sock'],[state/'broker-private'],docker_socket(),inbound_port=port),sys.executable,'-c',script],check=True)
   report['cases']['central_outbound_tcp_still_denied']=True
   switch.stop();switch.command('bootstrap',switch.domain,str(plist));wait_for(lambda:verify_new(state,key,release_info()['candidate']))
   assert hashlib.sha256((state/'config.yaml').read_bytes()).hexdigest()==cfg_hash
   assert request(port,'/v1/models',client_b)[0]==200
   report['cases']['restart_preserves_configuration_and_access']=True
   rotated='fictional-new-management-password'
   value=json.loads((state/'config.yaml').read_text());value['management']['secret-key']=rotated
   (state/'config.yaml').write_text(json.dumps(value));switch.stop();switch.command('bootstrap',switch.domain,str(plist))
   wait_for(lambda:verify_new(state,rotated,release_info()['candidate']))
   report['cases']['management_password_change_does_not_break_internal_controller']=True
   switch.restore(old_ok);assert plistlib.loads(plist.read_bytes())==original
   report['cases']['explicit_rollback_restores_old_service']=True
   failed=Switch(plist,root/'failed-switch',port);broken=dict(new,ProgramArguments=['/usr/bin/false'],KeepAlive=False)
   def fail():raise RuntimeError('injected_readiness_failure')
   try:failed.apply(broken,fail,old_ok)
   except RuntimeError as e:assert str(e)=='injected_readiness_failure',str(e)
   else:raise AssertionError('expected failure')
   assert old_ok() and plistlib.loads(plist.read_bytes())==original
   report['cases']['failed_upgrade_automatically_rolls_back']=True
   (ROOT/'evidence/mac-release-acceptance.json').write_text(json.dumps(report,indent=2))
  except BaseException:
   for name,path in [('old',old/'out.log'),('launcher',state/'launcher.log'),('launcher-error',state/'launcher-error.log'),('broker',state/'broker.log'),('central',state/'central.log')]:
    if path.exists():(ROOT/'evidence'/('failed-mac-'+name+'.log')).write_bytes(path.read_bytes()[-12000:])
   raise
  finally:
   subprocess.run(['launchctl','bootout',job],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
   for _ in range(50):
    if not (state/'launch.json').exists():break
    time.sleep(.1)
   subprocess.run(cli+['network','rm',network],check=True,stdout=subprocess.DEVNULL)
 print(json.dumps(report,indent=2))
if __name__=='__main__':run()

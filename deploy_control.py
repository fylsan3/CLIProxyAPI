"""Publish control/UI-only corrections without replacing account containers."""
import hashlib,json,plistlib,time
from pathlib import Path
from mac_release import Switch,copy_release,make_plist,atomic,request,wait_for
from retention import read_json,write_json
from version import release_info
ROOT=Path(__file__).resolve().parent

def deploy():
 home=Path.home()/'Library/Application Support/CPAContainer';state=home/'state';private=state/'broker-private';view=read_json(private/'central-view.json');port,key=view['port'],view['key']
 def snapshot():
  code,b=request(port,'/v8/management/account-environments/snapshot',key)
  if code!=200:raise ValueError('management_unavailable')
  return json.loads(b)
 plist=Path.home()/'Library/LaunchAgents/com.local.cliproxyapi.plist';saved=plistlib.loads(plist.read_bytes());args=saved['ProgramArguments']
 oldroot=Path(next(x for x in args if x.endswith('/launch.py'))).parent
 old_manifest=json.loads((oldroot/'release-manifest.json').read_text());new_manifest=json.loads((ROOT/'release-manifest.json').read_text());release_info()
 if old_manifest['images']!=new_manifest['images']:raise ValueError('control_update_image_changed')
 for name in ('central/cli-proxy-api','central/cli-proxy-api-linux-arm64','image/worker'):
  if old_manifest['files'][name]!=new_manifest['files'][name]:raise ValueError('control_update_binary_changed')
 before=snapshot()
 if before.get('scheduler_in_flight')!=0 or any(p.get('state',{}).get('active_calls') or p.get('state',{}).get('refreshing') or p.get('state',{}).get('authorization_pending') for p in before['projects']):raise ValueError('account_not_idle')
 cfg_hash=hashlib.sha256((state/'config.yaml').read_bytes()).hexdigest()
 release=home/'releases'/(new_manifest['candidate']+'-control-'+str(int(time.time())));copy_release(ROOT,release)
 network=Path(args[args.index('--network-config')+1]);backup=Path(args[args.index('--backup-directory')+1]);tx=home/'transactions'/('control-'+str(int(time.time())));switch=Switch(plist,tx,port)
 def ready():
  after=snapshot()
  old={p['slug']:p for p in before['projects']}
  return len(after['projects'])==len(old) and all(p['container']==old[p['slug']]['container'] and p.get('state',{}).get('authorized')==old[p['slug']].get('state',{}).get('authorized') for p in after['projects'])
 switch.apply(make_plist(switch.label,release,state,network,backup),ready,lambda:request(port,'/healthz')[0]==200)
 if hashlib.sha256((state/'config.yaml').read_bytes()).hexdigest()!=cfg_hash:raise ValueError('configuration_changed')
 wait_for(lambda:all(p.get('portable_backup',{}).get('state')=='exported' and not p['portable_backup'].get('warning') for p in snapshot()['projects']),seconds=120)
 result={'deployed':True,'release':str(release),'same_containers':True,'configuration_unchanged':True,'real_model_requests_sent':0,'authorization_started':False,'current_environment_backup_verified':True,'accounts_ready':[p.get('overall_ready') for p in snapshot()['projects']]}
 write_json(home/'management3-control-deployment.json',result);(ROOT/'evidence/production-control-upgrade.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
if __name__=='__main__':deploy()

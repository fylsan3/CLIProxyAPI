"""Authorized production upgrade. Readiness checks never call provider endpoints."""
import hashlib,json,plistlib,time
from pathlib import Path
from mac_release import Switch,copy_release,make_plist,atomic,request,wait_for
from upgrade_accounts import migrate,rollback
from retention import read_json,write_json
from host_runtime import docker_cli
from version import VERSION,release_info
import subprocess
ROOT=Path(__file__).resolve().parent

def deploy():
 home=Path.home()/'Library/Application Support/CPAContainer';state=home/'state';private=state/'broker-private'
 view=read_json(private/'central-view.json');port=view['port'];key=view['key']
 def snapshot():
  code,raw=request(port,'/v8/management/account-environments/snapshot',key)
  if code!=200:raise ValueError('management_unavailable')
  return json.loads(raw)
 before=snapshot();projects=before['projects']
 if not projects:raise ValueError('existing_accounts_required')
 for p in projects:
  if not p.get('state',{}).get('authorized') or p['state'].get('active_calls') or p['state'].get('refreshing') or p['state'].get('authorization_pending'):raise ValueError('account_not_idle')
 cfg=state/'config.yaml';cfg_hash=hashlib.sha256(cfg.read_bytes()).hexdigest()
 release_info()
 release=home/'releases'/(VERSION+'-'+str(int(time.time())));copy_release(ROOT,release)
 plist=Path.home()/'Library/LaunchAgents/com.local.cliproxyapi.plist';old=plistlib.loads(plist.read_bytes());args=old['ProgramArguments']
 network=Path(args[args.index('--network-config')+1]);backup=Path(args[args.index('--backup-directory')+1])
 tx=home/'transactions'/(VERSION+'-'+str(int(time.time())));switch=Switch(plist,tx,port);switch.backup();migrations=[];new_started=False
 try:
  # Re-read just before the maintenance window; account worker checks again after shutdown.
  if any(p.get('state',{}).get('active_calls') for p in snapshot()['projects']):raise ValueError('account_became_busy')
  switch.stop()
  for p in projects:migrations.append(migrate(state,p['slug'].upper()))
  atomic(plist,plistlib.dumps(make_plist(switch.label,release,state,network,backup)));switch.status('switching')
  switch.command('bootstrap',switch.domain,str(plist));new_started=True
  def ready():
   if request(port,'/healthz')[0]!=200:return False
   snap=snapshot()
   return len(snap['projects'])==len(projects) and all(p.get('state',{}).get('authorized') and p.get('ready') for p in snap['projects'])
  wait_for(ready,seconds=60)
  if hashlib.sha256(cfg.read_bytes()).hexdigest()!=cfg_hash:raise ValueError('configuration_changed')
  switch.status('active')
 except BaseException:
  if new_started:switch.stop()
  for item in reversed(migrations):rollback(state,item['transaction'])
  atomic(plist,(tx/'previous.plist').read_bytes());switch.command('bootstrap',switch.domain,str(plist));wait_for(lambda:request(port,'/healthz')[0]==200);switch.status('rolled_back');raise
 # Export only existing committed backups; no account/browser/model operation.
 for p in projects:
  code,raw=request(port,'/v8/management/account-environments/action',key,method='POST',body={'action':'backup-export','slug':p['slug']})
  if code not in (200,202):raise ValueError('backup_export_enqueue_failed')
 deadline=time.monotonic()+120
 while time.monotonic()<deadline:
  after=snapshot()
  if all(p.get('portable_backup',{}).get('state')=='exported' and not p['portable_backup'].get('warning') and not p['portable_backup'].get('environment_outdated') for p in after['projects']):break
  time.sleep(1)
 if not all(p.get('portable_backup',{}).get('state')=='exported' and not p['portable_backup'].get('warning') for p in after['projects']):raise ValueError('release_active_backup_pending')
 report={'deployed':True,'release':str(release),'transaction':str(tx),'configuration_unchanged':hashlib.sha256(cfg.read_bytes()).hexdigest()==cfg_hash,'real_model_requests_sent':0,'authorization_started':False,'manual_refresh_started':False,'management_url':'http://127.0.0.1:'+str(port)+'/accounts.html','accounts':[]}
 for p in after['projects']:
  report['accounts'].append({'slug':p['slug'],'ready':p.get('overall_ready'),'backup':p.get('portable_backup'),'state':{k:p.get('state',{}).get(k) for k in ['revision','expires','last_refresh','next_refresh','subscription']}})
 write_json(home/'management3-deployment.json',report);(ROOT/'evidence/production-upgrade-result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':deploy()

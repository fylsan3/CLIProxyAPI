"""Explicit stopped-controller upgrade, preserving environment and rollback volumes."""
import argparse,base64,copy,json,sqlite3,subprocess,time,uuid
from pathlib import Path
from lifecycle import Lease
from retention import read_json,write_json
from network_control import Control,DOCKER,docker,ROOT

def health(card):
 p=subprocess.run(DOCKER+['exec','--user','1001:1001','-i',card['container'],'/opt/native/worker','call'],input='{"path":"/health","body":{}}\n',capture_output=True,text=True,timeout=10,check=True)
 frames=[json.loads(x) for x in p.stdout.splitlines()];assert frames[0]['status']==200
 return json.loads(b''.join(base64.b64decode(f['body']) for f in frames if 'body' in f))
def migrate(state,owner):
 folder=Path(state)/'broker-private';lease=Lease(folder/'control.lock');control=None
 transaction=folder/('upgrade-'+owner+'-'+uuid.uuid4().hex[:12]+'.json');stopped=False;committed=False;new=None
 try:
  control=Control(folder/'environments');old=read_json(control.card(owner));info=control.inspect(old)
  # The old container is inspected against its own immutable card, never admitted by the new pool.
  current=health(old)
  if current.get('active_calls') or current.get('refreshing') or current.get('account_updating') or current.get('authorization_pending'):raise ValueError('account_busy')
  if not current.get('authorized'):raise ValueError('existing_authorization_required')
  old_protection=read_json(control.folder/('protection-'+owner+'.json'))
  if not old_protection.get('backup_verified'):raise ValueError('verified_backup_required')
  runtime=json.loads(docker('run','--rm','--pull=never','--network','none','--user','1001:1001','-e','NETWORK_STAGE=maintenance','-e','TZ='+old['runtime']['timezone'],'--entrypoint','python3',control.image,'-B','/opt/native/retention_cli.py','inventory'))
  if {k:v for k,v in runtime.items() if k!='worker_sha256'}!={k:v for k,v in old['runtime'].items() if k!='worker_sha256'}:raise ValueError('environment_change_rejected')
  new=copy.deepcopy(old);new.update(image=control.image,runtime=runtime,hostname=info['Config']['Hostname'])
  suffix='-upgrade-'+uuid.uuid4().hex[:8]
  for key in ('volume','backup'):new[key]=old[key]+suffix
  record={'old':old,'new':new,'old_protection':old_protection,'phase':'prepared'};write_json(transaction,record)
  # Flush a live browser profile before copying its data. Never reopen or reauthorize it.
  def browser(op):
   p=subprocess.run(DOCKER+['exec','--user','1001:1001','-i',old['container'],'python3','-B','/opt/sample/worker.py','request'],input=json.dumps({'op':op}),capture_output=True,text=True,timeout=25,check=True)
   value=json.loads(p.stdout)
   if value.get('error') or value.get('owner')!=owner:raise ValueError('browser_profile_close_unverified')
   return value
  if browser('status').get('browser'):
   closed=browser('close-browser')
   if closed.get('browser') or closed.get('browser_close')!='graceful':raise ValueError('browser_profile_close_unverified')
  # Drain completed before entry; never authorizes or refreshes an account.
  docker('stop','-t','30',old['container']);stopped=True
  for key in ('volume','backup'):docker('volume','create','--label','cpa.retention.id='+old['environment_id'],new[key])
  args=DOCKER+['run','--rm','-i','--network','none','--read-only','--user','1001:1001','--cap-drop','ALL','--entrypoint','python3']
  for name,target,ro in [(old['volume'],'/old-state',True),(old['backup'],'/old-backup',True),(new['volume'],'/state',False),(new['backup'],'/backup',False)]:args+=['--mount','type=volume,source='+name+',target='+target+(',readonly' if ro else '')]
  script=(ROOT/'image/migrate_runtime.py').read_text()
  p=subprocess.run(args+[control.image,'-B','-c',script],input=json.dumps({'old':old,'new':new,'snapshot':old_protection['snapshot']}),text=True,capture_output=True,timeout=300)
  if p.returncode:raise ValueError('offline_migration_failed: '+p.stderr[-500:])
  proof=json.loads(p.stdout);new['container']=docker('create',*control.args(new,runtime=True),new['image'])
  record.update(new=new,proof=proof,phase='cloned');write_json(transaction,record)
  docker('start',new['container']);control.wait_started(new)
  observed=health(new)
  if not observed.get('authorized') or observed.get('revision')!=current.get('revision'):raise ValueError('credential_restore_unverified')
  # Health only: no model, refresh, browser or profile endpoint call.
  protection=dict(old_protection,manifest_sha256=proof['manifest_sha256'],verified_at=int(time.time()))
  with sqlite3.connect(folder/'control.sqlite') as db:
   row=db.execute('SELECT container FROM bindings WHERE owner=?',(owner,)).fetchone()
   if row!=(old['container'],):raise ValueError('binding_changed')
   write_json(control.card(owner),new);write_json(control.folder/('protection-'+owner+'.json'),protection)
   db.execute('UPDATE bindings SET container=? WHERE owner=?',(new['container'],owner))
  record.update(phase='committed',new_protection=protection);write_json(transaction,record);committed=True
  return {'transaction':str(transaction),'environment_preserved':True,'credentials_unchanged':True,'old_container_preserved':True,'new_container':new['container']}
 finally:
  if stopped and not committed:
   if new and new.get('container') and new['container']!=old['container']:
    try:docker('stop','-t','15',new['container'])
    except Exception:pass
   write_json(control.card(owner),old);write_json(control.folder/('protection-'+owner+'.json'),old_protection)
   with sqlite3.connect(folder/'control.sqlite') as db:db.execute('UPDATE bindings SET container=? WHERE owner=?',(old['container'],owner))
   docker('start',old['container'])
   if transaction.exists():record['phase']='rolled_back';write_json(transaction,record)
  if control:control.close()
  lease.close()
def rollback(state,transaction):
 folder=Path(state)/'broker-private';lease=Lease(folder/'control.lock')
 try:
  record=read_json(Path(transaction));old,new=record['old'],record['new']
  if record['phase']!='committed':raise ValueError('committed_upgrade_required')
  active=read_json(folder/'environments'/(old['owner']+'.json'))
  if active!=new:raise ValueError('active_card_changed')
  current=health(new)
  if current.get('active_calls') or current.get('refreshing'):raise ValueError('account_busy')
  docker('stop','-t','30',new['container'])
  script="import hashlib;from pathlib import Path;print(hashlib.sha256(Path('/state/native-auth.json').read_bytes()).hexdigest())"
  observed=docker('run','--rm','--pull=never','--network','none','--read-only','--user','1001:1001','--mount','type=volume,source='+new['volume']+',target=/state,readonly','--entrypoint','python3',new['image'],'-c',script)
  if observed!=record['proof']['credential_sha256']:
   docker('start',new['container']);raise ValueError('new_credentials_exist_no_rollback')
  with sqlite3.connect(folder/'control.sqlite') as db:
   write_json(folder/'environments'/(old['owner']+'.json'),old)
   write_json(folder/'environments'/('protection-'+old['owner']+'.json'),record['old_protection'])
   db.execute('UPDATE bindings SET container=? WHERE owner=?',(old['container'],old['owner']))
  docker('start',old['container']);record['phase']='rolled_back';write_json(Path(transaction),record)
  return {'rolled_back':True,'credentials_unchanged':True}
 finally:lease.close()

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--state',type=Path,required=True);p.add_argument('--owner',required=True);a=p.parse_args();print(json.dumps(migrate(a.state,a.owner)))

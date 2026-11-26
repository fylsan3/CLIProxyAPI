"""Bounded local-only capture collector. Never sends a provider request.
Private archive and keys remain in each account container. Only sanitized fixtures
are written into samples/captured. Notification payload contains no account data.
"""
import argparse,json,os,subprocess,time
from pathlib import Path
from host_runtime import docker_cli
from sample_status import response_review,review_issues
ROOT=Path(__file__).resolve().parent

def atomic(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp')
 with tmp.open('w') as f:os.chmod(tmp,0o600);json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
 os.replace(tmp,path)
def execute(container,script,payload=None):
 r=subprocess.run(docker_cli()+['exec','--user','1001:1001','-i',container,'python3','-B','-c',script],input=json.dumps(payload or {}),text=True,capture_output=True,timeout=45)
 if r.returncode:raise RuntimeError('container_capture_operation_failed')
 return json.loads(r.stdout)
STATUS="""import json,sys
from pathlib import Path
sys.path.insert(0,'/opt/native');import sample_export
root=Path('/state');a=root/'header-audit.json';w=root/'capture-window.json';base=root/'http-samples'
print(json.dumps({'body_export_version':getattr(sample_export,'BODY_EXPORT_VERSION',1),'audit':json.loads(a.read_text()) if a.exists() else {},'window':json.loads(w.read_text()) if w.exists() else {},'archives':{x.name:[f.name for f in x.iterdir() if f.is_dir()] for x in base.iterdir() if x.is_dir()} if base.exists() else {}}))
"""
ARM="""import json,os,sys
from pathlib import Path
v=json.load(sys.stdin);p=Path('/state/capture-window.json');t=p.with_suffix('.tmp')
with t.open('w') as f:os.chmod(t,0o600);json.dump(v,f);f.flush();os.fsync(f.fileno())
os.replace(t,p);print('{"armed":true}')
"""
EXPORT="""import json,sys
sys.path.insert(0,'/opt/native');import sample_export
v=json.load(sys.stdin);print(json.dumps(sample_export.export('/state',only=set(v['archives']),skip=set(v['skip'])),ensure_ascii=False))
"""
def cards(state):
 out=[]
 for p in (state/'broker-private/environments').glob('*.json'):
  v=json.loads(p.read_text())
  if all(k in v for k in ('container','owner','environment_id')):out.append(v)
 return out
def watch(state,destination,record,arm=False,hours=24,once=False,arm_only=False):
 if arm:
  if hours<=0 or hours>24:raise ValueError('test_window_must_be_0_to_24_hours')
  config={'expires':int(time.time()+hours*3600),'accounts':{},'source_root':str(ROOT)}
  for card in cards(state):
   observed=execute(card['container'],STATUS)
   config['accounts'][card['owner']]={'environment_id':card['environment_id'],'skip':list(observed['archives']),'exported':[],'alert_signatures':[]}
   execute(card['container'],ARM,{'enabled':True,'expires':config['expires']})
  atomic(record,config)
  if arm_only:return
 else:config=json.loads(record.read_text())
 while time.time()<config['expires']:
  for card in cards(state):
   account=config['accounts'].get(card['owner'])
   if not account or account['environment_id']!=card['environment_id']:continue
   try:
    status=execute(card['container'],STATUS);audit=status['audit'];account['audit']=audit
    # Re-export only previously selected old compressed fixtures. The original
    # encrypted archive and window/skip selection are never changed.
    if status.get('body_export_version',1)>=2 and account.get('body_export_migration')!=2:
     upgrade=[]
     for sid in account['exported']:
      path=destination/(sid+'.json')
      if not path.exists():continue
      sample=json.loads(path.read_text())
      if sample.get('body_export_version',1)<2 and any(sample.get(side,{}).get('body',{}).get('format')=='encoded_or_binary_redacted' for side in ('request','response')):upgrade.append(sid)
     account['body_export_pending']=upgrade;account['body_export_migration']=2
    upgrades=set(account.get('body_export_pending',[])) if status.get('body_export_version',1)>=2 else set()
    pending=[a for a,exchanges in status['archives'].items() if a not in account['skip'] and any(a+'-'+e not in account['exported'] for e in exchanges)][:20]
    pending=list(dict.fromkeys(pending+[sid.rsplit('-',1)[0] for sid in sorted(upgrades)]))[:20]
    changed_samples=set()
    if pending:
     exported=execute(card['container'],EXPORT,{'archives':pending,'skip':[sid for sid in account['exported'] if sid not in upgrades]})
     changed_samples={s['sample_id'] for s in exported.get('samples',[])}
     for sample in exported.get('samples',[]):
      sample['response_review']=response_review(sample)
      atomic(destination/(sample['sample_id']+'.json'),sample)
      account['latest_response_review']={'sample_id':sample['sample_id'],**sample['response_review']}
      if sample.get('body_export_version',1)>=2:upgrades.discard(sample['sample_id'])
     if status.get('body_export_version',1)>=2:account['body_export_pending']=sorted(upgrades)
     incomplete={x['sample_id'] for x in exported.get('pending',[])}
     # Only close an archive if an exchange was actually exported and none is pending.
     completed={x['sample_id'] for x in exported.get('samples',[])}-incomplete
     account['exported']=sorted(set(account['exported'])|completed)
    # Reclassify already exported sanitized samples too; no account/upstream request.
    reviews={};history={x['sample_id']:x for x in account.get('capture_issue_history',[])}
    for sample_id in account['exported']:
     if account.get('review_version')==2 and sample_id not in changed_samples and not sample_id.startswith(audit.get('last_archive','!')+'-'):continue
     path=destination/(sample_id+'.json')
     if not path.exists():continue
     sample=json.loads(path.read_text());review=response_review(sample)
     if sample.get('response_review')!=review:sample['response_review']=review;atomic(path,sample)
     codes=review_issues(review)
     if codes:history[sample_id]={'sample_id':sample_id,'codes':codes}
     else:history.pop(sample_id,None)
     if sample_id.startswith(audit.get('last_archive','!')+'-'):reviews[sample_id]=review
    account['latest_response_reviews']=reviews
    account['capture_issue_history']=list(history.values())[-32:]
    archive=audit.get('last_archive','')
    account['latest_expected_samples']=[archive+'-'+e for e in status['archives'].get(archive,[])]
    account['review_version']=2
    for alert in audit.get('alerts',[]):
     signature=json.dumps(alert,sort_keys=True)
     if signature not in account['alert_signatures']:
      account['alert_signatures'].append(signature)
      if os.uname().sysname=='Darwin':subprocess.run(['/usr/bin/osascript','-e','display notification "检测到请求头差异或未分类字段，请查看 CPA 账号管理详情。" with title "CPA 请求头检查"'],capture_output=True,timeout=5)
    account['last_check']=int(time.time());account.pop('error',None)
   except Exception:account['error']='capture_monitor_or_export_failed'
  config['updated_at']=int(time.time());atomic(record,config)
  if once:return
  time.sleep(5)
 config['finished']=True;atomic(record,config)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--state',type=Path,required=True);p.add_argument('--destination',type=Path,required=True);p.add_argument('--record',type=Path,required=True);p.add_argument('--arm',action='store_true');p.add_argument('--hours',type=float,default=24);p.add_argument('--once',action='store_true');p.add_argument('--arm-only',action='store_true');a=p.parse_args()
 watch(a.state,a.destination,a.record,a.arm,a.hours,a.once,a.arm_only)

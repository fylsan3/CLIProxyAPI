"""Install the authorized bounded capture collector as a per-user macOS service.
It only reads local account archives. It never calls an account/provider endpoint.
"""
import argparse,json,os,plistlib,subprocess,sys,time
from pathlib import Path
from capture_watch import atomic
ROOT=Path(__file__).resolve().parent
LABEL='com.local.cpa.capture-monitor'

def install(state,destination,hours=24,resume=False):
 if sys.platform!='darwin':raise ValueError('macos_service_only')
 state=state.resolve();destination=destination.resolve();destination.mkdir(parents=True,exist_ok=True);destination.chmod(0o700)
 domain='gui/'+str(os.getuid());record=state/'capture-monitor.json';plist=Path.home()/'Library/LaunchAgents'/ (LABEL+'.plist')
 if resume:
  existing=json.loads(record.read_text())
  if existing['expires']<=time.time():raise ValueError('existing_capture_window_expired')
 # Remove only our existing job; do not touch the CPA service or other agents.
 prior=subprocess.run(['launchctl','print',domain+'/'+LABEL],capture_output=True)
 if prior.returncode==0:subprocess.run(['launchctl','bootout',domain+'/'+LABEL],capture_output=True,check=True)
 # Retire a legacy detached collector only after checking its executable arguments.
 pidfile=state/'capture-monitor.pid'
 if pidfile.exists():
  try:pid=int(pidfile.read_text())
  except ValueError:pid=0
  if pid>1:
   command=subprocess.run(['ps','-p',str(pid),'-o','command='],capture_output=True,text=True).stdout
   if 'capture_watch.py' in command and str(record) in command:
    os.kill(pid,15)
    for _ in range(50):
     try:os.kill(pid,0)
     except ProcessLookupError:break
     time.sleep(.1)
    else:raise ValueError('legacy_collector_still_running')
 command=[sys.executable,'-B',str(ROOT/'capture_watch.py'),'--state',str(state),'--destination',str(destination),'--record',str(record)]
 if not resume:subprocess.run(command+['--arm','--arm-only','--hours',str(hours)],check=True)
 started=int(time.time())
 config={'Label':LABEL,'ProgramArguments':command,'RunAtLoad':True,'KeepAlive':{'SuccessfulExit':False},'ThrottleInterval':10,'ProcessType':'Background','StandardOutPath':str(state/'capture-monitor-service.log'),'StandardErrorPath':str(state/'capture-monitor-service.log')}
 plist.parent.mkdir(parents=True,exist_ok=True)
 tmp=plist.with_suffix('.tmp');tmp.write_bytes(plistlib.dumps(config));tmp.chmod(0o600);os.replace(tmp,plist)
 subprocess.run(['launchctl','bootstrap',domain,str(plist)],check=True)
 deadline=time.monotonic()+35
 while time.monotonic()<deadline:
  v=json.loads(record.read_text())
  if v.get('updated_at',0)>=started and v['accounts'] and all(a.get('last_check',0)>=started and not a.get('error') for a in v['accounts'].values()):
   receipt={'installed':True,'label':LABEL,'expires':v['expires'],'collector_local_only':True,'destination':str(destination),'accounts':len(v['accounts'])}
   atomic(state/'capture-monitor-service.json',receipt);return receipt
  time.sleep(.5)
 raise ValueError('collector_not_ready; inspect local service log')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--state',type=Path,required=True);p.add_argument('--destination',type=Path,required=True);p.add_argument('--hours',type=float,default=24);p.add_argument('--resume',action='store_true',help='Keep the existing capture window and archive selection');a=p.parse_args();print(json.dumps(install(a.state,a.destination,a.hours,a.resume),indent=2))

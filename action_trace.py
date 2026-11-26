"""Local management receipts; never store request bodies, credentials or replies."""
import contextvars,json,os,threading,time,uuid
from contextlib import contextmanager
from pathlib import Path

current=contextvars.ContextVar('management_action_trace',default=None)
lock=threading.Lock()

def stage(name,**fields):
    trace=current.get()
    if trace is None:return
    event={'stage':name,'at':time.time(),**fields}
    trace['events'].append(event)
    row={k:v for k,v in trace.items() if k!='folder'}
    folder=trace['folder']/'action-receipts'
    try:
        with lock:
            folder.mkdir(mode=0o700,exist_ok=True)
            path=folder/(trace['slug']+'.json');tmp=path.with_suffix('.tmp')
            fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(fd,'w') as f:json.dump(row,f);f.flush();os.fsync(f.fileno())
            os.replace(tmp,path)
    except OSError:
        trace['receipt_save_failed']=True
    print(json.dumps({'event':'account_management_action','operation_id':trace['operation_id'],'action':trace['action'],'slug':trace['slug'],**event}),flush=True)

@contextmanager
def tracking(broker,slug,action):
    trace={'folder':Path(broker.folder),'operation_id':uuid.uuid4().hex,'slug':slug,'action':action,'events':[]}
    token=current.set(trace)
    try:
        stage('controller_received')
        yield trace
    finally:current.reset(token)

def latest(folder,slug):
    try:
        value=json.loads((Path(folder)/'action-receipts'/(slug+'.json')).read_text())
        return value if value.get('slug')==slug else None
    except (OSError,ValueError):return None

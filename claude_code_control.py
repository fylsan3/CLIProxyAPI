"""Account-bound bridge. No CLI credentials or shell commands enter the controller."""
import json,select,socket,subprocess,time
from account_identity import valid_slug
from host_runtime import docker_cli

OPS={'status','job-start','job-read','job-cancel','terminal-start','terminal-read','terminal-input','terminal-resize','terminal-stop'}
FIELDS={
 'status':set(),'job-start':{'prompt','model'},'job-read':{'id'},'job-cancel':{'id'},
 'terminal-start':{'mode','cols','rows'},'terminal-read':{'id','offset'},
 'terminal-input':{'id','data'},'terminal-resize':{'id','cols','rows'},'terminal-stop':{'id'}}

def command(broker,slug,op,values):
    if not valid_slug(slug) or op not in OPS or set(values)-FIELDS[op]:return 400,{'error':'invalid_claude_request'}
    try:owner=broker.registry.get(slug)['owner']
    except ValueError:return 400,{'error':'account_not_registered'}
    info=broker.inspect(owner)
    if not info or not info['State']['Running']:return 503,{'error':'container_unavailable'}
    result=subprocess.run(docker_cli()+['exec','--user','1001:1001','-i',info['Id'],'python3','-B','/opt/native/claude_code.py','call'],
                          input=json.dumps(dict(values,op=op)),text=True,capture_output=True,timeout=50)
    if result.returncode:return 503,{'error':'claude_code_not_installed_or_unavailable'}
    try:data=json.loads(result.stdout)
    except ValueError:return 502,{'error':'invalid_claude_receipt'}
    data['account']=slug;data['container']=info['Id'][:12]
    return (409 if data.get('error') else 200),data

def action(broker,body):
    op=str(body.get('action','')).removeprefix('claude-')
    slug=body.get('slug')
    if op=='browser-open':
        if set(body)!={'action','slug'} or not valid_slug(slug):return 400,{'error':'invalid_claude_request'}
        owner=broker.registry.get(slug)['owner']
        return 200,broker.browsers.open(owner)
    return command(broker,slug,op,{k:v for k,v in body.items() if k not in ('action','slug')})

def disconnected(connection):
    if connection is None:return False
    ready,_,_=select.select([connection],[],[],0)
    try:return bool(ready and connection.recv(1,socket.MSG_PEEK|socket.MSG_DONTWAIT)==b'')
    except BlockingIOError:return False

def message(broker,body,connection=None):
    if not isinstance(body,dict) or set(body)-{'account','prompt','model'}:return 400,{'error':'invalid_claude_request'}
    slug=body.get('account')
    if not valid_slug(slug):return 400,{'error':'invalid_account'}
    try:owner=broker.registry.get(slug)['owner']
    except ValueError:return 400,{'error':'account_not_registered'}
    with broker.gate.request(owner):
        code,result=command(broker,slug,'job-start',{k:body[k] for k in ('prompt','model') if k in body})
        if code!=200:return code,result
        ident=result['id'];complete=False
        try:
            deadline=time.monotonic()+7210
            while time.monotonic()<deadline:
                if disconnected(connection):return 499,{'error':'client_disconnected','id':ident}
                code,result=command(broker,slug,'job-read',{'id':ident})
                if code!=200:return code,result
                if result['state'] not in ('starting','running','cleaning'):
                    complete=True
                    # Keep official CLI's result event intact, including usage and errors.
                    return (200 if result['state']=='succeeded' else 502),result
                time.sleep(.5)
            return 504,{'error':'claude_wait_timeout','id':ident}
        finally:
            if not complete:
                try:command(broker,slug,'job-cancel',{'id':ident})
                except (OSError,ValueError,subprocess.SubprocessError):pass

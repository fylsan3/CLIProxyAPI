"""Mac empty-account deployment with explicit state and a reversible launchd switch."""
import argparse,copy,hashlib,http.client,json,os,plistlib,re,secrets,shutil,socket,subprocess,sys,tempfile,time
from pathlib import Path
from storage_guard import private_directory,private_file
from saved_config import create_private
ROOT=Path(__file__).resolve().parent

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write_json(path,value):create_private(path,json.dumps(value,ensure_ascii=False,indent=2).encode())
def load_yaml(path):
    result=subprocess.run(['/usr/bin/ruby','-rjson','-ryaml','-e','print JSON.generate(YAML.safe_load(File.read(ARGV[0]), aliases: true))',str(path)],capture_output=True,text=True,check=True)
    value=json.loads(result.stdout)
    if not isinstance(value,dict):raise ValueError('configuration_object_required')
    return value

def prepare_state(source,state,key,backup,port=None,host=None):
    """Preserve all settings except an explicit empty account directory and test overrides."""
    if state.exists():raise ValueError('existing_state_not_overwritten')
    original=load_yaml(source)
    if original.get('config-version')!=8:raise ValueError('v8_configuration_required')
    cfg=copy.deepcopy(original);state.mkdir(mode=0o700,parents=True);private_directory(state)
    private_directory(state/'auth-empty');backup.mkdir(mode=0o700,parents=True,exist_ok=True);private_directory(backup)
    cfg.setdefault('oauth',{})['auth-dir']=str(state/'auth-empty')
    if port is not None:cfg['server']['port']=port
    if host is not None:cfg['server']['host']=host
    if not isinstance(key,str) or not 1<=len(key.encode())<=72 or any(c in key for c in '\r\n'):raise ValueError('management_key_invalid')
    write_json(state/'config.yaml',cfg);create_private(state/'client-key',secrets.token_hex(24).encode())
    # This comparison includes every client API key without logging any key value.
    comparable=copy.deepcopy(cfg);comparable['oauth']['auth-dir']=original.get('oauth',{}).get('auth-dir')
    if port is not None:comparable['server']['port']=original['server']['port']
    if host is not None:comparable['server']['host']=original['server'].get('host','')
    if comparable!=original:raise ValueError('unintended_configuration_change')
    from saved_config import prepare
    prepare(ROOT,state,production=True)
    return {'source_sha256':digest(source),'configuration_preserved_except_auth_directory':True,'port':cfg['server']['port'],'host':cfg['server'].get('host',''),'api_key_count':len(cfg.get('access',{}).get('api-keys',[]))}

def make_plist(label,release,state,network,backup):
    if not label.startswith('com.local.') or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-' for c in label):raise ValueError('invalid_service_label')
    return {'Label':label,'ProgramArguments':['/usr/bin/python3','-B',str(release/'launch.py'),'--production','--state',str(state),'--network-config',str(network),'--backup-directory',str(backup)],
            'WorkingDirectory':str(state),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,'ExitTimeOut':3700,'ProcessType':'Interactive',
            'EnvironmentVariables':{'PATH':'/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin','HOME':str(Path.home())},
            'StandardOutPath':str(state/'launcher.log'),'StandardErrorPath':str(state/'launcher-error.log')}

def local_ipv4():
    raw=subprocess.check_output(['/sbin/ifconfig'],text=True)
    return [ip for ip in re.findall(r'\binet (\d+\.\d+\.\d+\.\d+)',raw) if not ip.startswith(('127.','169.254.'))]

def request(port,path,key=None,method='GET',body=None,host='127.0.0.1'):
    c=http.client.HTTPConnection(host,port,timeout=5)
    try:
        headers={'Authorization':'Bearer '+key} if key else {}
        if body is not None:headers['Content-Type']='application/json'
        c.request(method,path,json.dumps(body) if body is not None else None,headers)
        res=c.getresponse();raw=res.read();return res.status,raw
    finally:c.close()

def wait_for(check,seconds=45):
    end=time.monotonic()+seconds
    while time.monotonic()<end:
        try:
            if check():return
        except (OSError,ValueError,KeyError,http.client.HTTPException):pass
        time.sleep(.2)
    raise RuntimeError('release_readiness_failed')

def atomic(path,raw):
    fd,tmp=tempfile.mkstemp(prefix='.cpa-release-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:os.fchmod(f.fileno(),0o600);f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:Path(tmp).unlink(missing_ok=True)

class Switch:
    def __init__(self,plist,transaction,port):
        self.plist=Path(plist);self.transaction=Path(transaction);self.port=port
        self.domain='gui/'+str(os.getuid());self.label=plistlib.loads(self.plist.read_bytes())['Label'];self.job=self.domain+'/'+self.label
    def command(self,*args,check=True):
        result=subprocess.run(['launchctl',*args],capture_output=True,text=True,timeout=45)
        if check and result.returncode:raise RuntimeError('launchctl_'+args[0]+'_failed')
        return result
    def running(self):return self.command('print',self.job,check=False).returncode==0
    def stop(self):
        if self.running():self.command('bootout',self.job)
        wait_for(lambda:not self.running())
        def free():
            try:
                with socket.create_connection(('127.0.0.1',self.port),timeout=.2):return False
            except OSError:return True
        wait_for(free)
    def backup(self):
        self.transaction.mkdir(mode=0o700,parents=True,exist_ok=False);private_directory(self.transaction)
        create_private(self.transaction/'previous.plist',self.plist.read_bytes())
        write_json(self.transaction/'switch.json',{'label':self.label,'port':self.port,'plist':str(self.plist),'previous_sha256':digest(self.plist),'status':'prepared'})
    def status(self,value):
        p=self.transaction/'switch.json';data=json.loads(p.read_text());data['status']=value;atomic(p,json.dumps(data,indent=2).encode())
    def restore(self,check):
        previous=self.transaction/'previous.plist'
        if digest(previous)!=json.loads((self.transaction/'switch.json').read_text())['previous_sha256']:raise ValueError('rollback_plist_changed')
        self.stop();atomic(self.plist,previous.read_bytes());self.command('bootstrap',self.domain,str(self.plist));wait_for(check);self.status('rolled_back')
    def apply(self,new_plist,check_new,check_old):
        self.backup()
        self.stop()
        try:
            atomic(self.plist,plistlib.dumps(new_plist));self.status('switching');self.command('bootstrap',self.domain,str(self.plist));wait_for(check_new);self.status('active')
        except BaseException:
            self.restore(check_old);raise

def verify_empty_old(port,key):
    status,raw=request(port,'/v8/management/credentials',key)
    if status!=200:raise ValueError('existing_management_authentication_failed')
    data=json.loads(raw);items=data.get('files',data.get('items',data.get('credentials')))
    if not isinstance(items,list) or items:raise ValueError('empty_existing_account_list_required')

def verify_new(state,key,expected_version):
    launch=state/'launch.json'
    if not launch.is_file():return False
    data=json.loads(launch.read_text());port=int(data['api_base'].split(':')[-1].split('/')[0])
    if not data.get('production') or data['release']['candidate']!=expected_version:return False
    status,raw=request(port,'/v8/management/account-environments/snapshot',key)
    if status!=200:return False
    snap=json.loads(raw)
    if snap.get('projects') or snap.get('offline_only') is not False or not snap.get('central_status_available'):return False
    if request(port,'/healthz')[0]!=200 or request(port,'/v1/models')[0]!=401:return False
    cfg=load_yaml(state/'config.yaml');keys=cfg['access']['api-keys']
    if any(request(port,'/v1/models',token)[0]!=200 for token in keys):return False
    if cfg['server'].get('host','') in ('','0.0.0.0'):
        for address in local_ipv4():
            if request(port,'/v1/models',keys[0],host=address)[0]!=200:return False
    page_status,page=request(port,'/accounts.html')
    return page_status==200 and '账号与运行状态'.encode() in page

def copy_release(source,destination):
    if destination.exists():raise ValueError('release_already_exists')
    sys.path.insert(0,str(source));from version import release_info
    release_info();manifest=json.loads((source/'release-manifest.json').read_text())
    destination.mkdir(mode=0o700,parents=True)
    for name,want in manifest['files'].items():
        src=source/name;dst=destination/name
        if Path(name).is_absolute() or '..' in Path(name).parts or src.is_symlink():raise ValueError('unsafe_release_path')
        if digest(src)!=want:raise ValueError('release_hash_mismatch')
        dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
    shutil.copy2(source/'release-manifest.json',destination/'release-manifest.json')
    return manifest['candidate']

def deploy(home,key):
    """Initial empty-account cutover only; later upgrades need a separate account-aware plan."""
    if sys.platform!='darwin':raise ValueError('mac_required')
    home=Path(home).resolve();old=Path.home()/'cliproxyapi';config=old/'config.yaml'
    source_config=load_yaml(config);port=source_config['server']['port']
    verify_empty_old(port,key)
    from version import release_info
    info=release_info()
    release=home/'releases'/info['candidate'];state=home/'state';backup=home/'account-backups'
    if state.exists() or release.exists():raise ValueError('existing_deployment_not_overwritten')
    home.mkdir(mode=0o700,parents=True,exist_ok=True);private_directory(home)
    before=digest(config)
    legacy=home/'legacy-backup';legacy.mkdir(mode=0o700,exist_ok=False)
    create_private(legacy/'config.yaml',config.read_bytes());shutil.copy2(old/'bin/cli-proxy-api',legacy/'cli-proxy-api')
    write_json(legacy/'digests.json',{'config':before,'binary':digest(old/'bin/cli-proxy-api')})
    copy_release(ROOT,release)
    report=prepare_state(config,state,key,backup)
    from host_runtime import docker_cli
    cli=docker_cli();scope=secrets.token_hex(12);network='cpa-production-'+scope
    subprocess.run(cli+['network','create','--driver','bridge','--label','cpa.account-network='+scope,network],check=True,stdout=subprocess.DEVNULL)
    network_file=home/'network.json';write_json(network_file,{'mode':'managed','scope':scope,'network':network})
    plist=Path.home()/'Library/LaunchAgents/com.local.cliproxyapi.plist';transaction=home/'transactions'/secrets.token_hex(8)
    controller=Switch(plist,transaction,port)
    if digest(config)!=before:raise ValueError('production_config_changed_during_preparation')
    verify_empty_old(port,key)
    controller.apply(make_plist(controller.label,release,state,network_file,backup),lambda:verify_new(state,key,info['candidate']),lambda:request(port,'/healthz')[0]==200)
    assert digest(config)==before
    report.update(deployed=True,candidate=info['candidate'],release=str(release),state=str(state),transaction=str(transaction),management_url='http://127.0.0.1:'+str(port)+'/accounts.html',old_configuration_unchanged=True,real_account_verified=False)
    write_json(home/'deployment.json',report);print(json.dumps(report,ensure_ascii=False,indent=2))

def rollback(home):
    home=Path(home).resolve();private_directory(home)
    record=json.loads((home/'deployment.json').read_text());state=Path(record['state'])
    registry=json.loads((state/'broker-private/accounts.json').read_text())
    if registry.get('accounts'):raise ValueError('accounts_exist_manual_rollback_review_required')
    transaction=Path(record['transaction']);saved=json.loads((transaction/'switch.json').read_text())
    plist=Path(saved['plist']);current=plistlib.loads(plist.read_bytes())
    if current.get('WorkingDirectory')!=str(state):raise ValueError('active_service_does_not_match_deployment')
    original=Path.home()/'cliproxyapi'
    digests=json.loads((home/'legacy-backup/digests.json').read_text())
    if digest(original/'config.yaml')!=digests['config'] or digest(original/'bin/cli-proxy-api')!=digests['binary']:raise ValueError('legacy_files_changed_manual_restore_required')
    controller=Switch(plist,transaction,record['port'])
    controller.restore(lambda:request(record['port'],'/healthz')[0]==200)
    record['deployed']=False;record['rolled_back']=True;atomic(home/'deployment.json',json.dumps(record,indent=2).encode())
    print('Previous service restored; account data and backups retained.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--home',type=Path,required=True);p.add_argument('--rollback',action='store_true');a=p.parse_args()
    if a.rollback:rollback(a.home)
    else:deploy(a.home,sys.stdin.readline().rstrip('\r\n'))

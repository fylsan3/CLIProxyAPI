"""Network-bound test lifecycle; never accepts real credentials or public proxy settings."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
from proxy_config import parse_proxy
from account_identity import valid_owner
from account_registry import Registry

ROOT = Path(__file__).resolve().parent
path = ROOT / 'retention_base.py'
spec = importlib.util.spec_from_file_location('retention_base_control', path)
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
DOCKER, docker = base.DOCKER, base.docker
from retention import read_json, write_json


class Control(base.Control):
    def __init__(self, folder):
        super().__init__(folder)
        self.registry=Registry(self.folder.parent)
        self.images=json.loads((ROOT / 'image.json').read_text());self.image=self.images['id']
        self.seccomp_path=ROOT/'security/seccomp.json'
        self.seccomp_sha256=hashlib.sha256(self.seccomp_path.read_bytes()).hexdigest()
        if self.seccomp_sha256!=json.loads((ROOT/'security/source.json').read_text())['sha256']:raise ValueError('container_policy_changed')
        self.seccomp=json.loads(self.seccomp_path.read_text())
        self.fixture = read_json(self.folder.parent / 'network-fixture.json')
        network = json.loads(docker('network', 'inspect', self.fixture['network']))[0]
        mode=self.fixture.get('mode','closed_test')
        if mode in ('closed_test','closed_tls_test'):
            if not network['Internal'] or network['Labels'].get('cpa.socks-lab')!=self.fixture['scope']:raise ValueError('closed_fixture_network_required')
            if mode=='closed_tls_test':self.image=self.images['tls_test']
        elif mode=='managed':
            if network['Internal'] or network['Labels'].get('cpa.account-network')!=self.fixture['scope']:raise ValueError('managed_network_binding_required')
        else:raise ValueError('network_mode_invalid')

    def card(self,owner):
        if not valid_owner(owner):raise ValueError('invalid_owner')
        self.registry.get(owner.lower())
        return self.folder/(owner+'.json')

    def args(self, card, state_volume=None, runtime=False):
        common = ['--pull=never', '--read-only', '--init', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                  '--memory','1g','--pids-limit','300','--shm-size','96m',
                  '--tmpfs','/tmp:rw,nosuid,nodev,size=192m,mode=1777',
                  '--label','cpa.retention.id='+card['environment_id'],
                  '--mount','type=volume,source='+(state_volume or card['volume'])+',target=/state',
                  '--mount','type=volume,source='+card['backup']+',target=/backup',
                  '--mount','type=volume,source='+card['network_config']+',target=/network-config,readonly',
                  '-e','TZ='+card['runtime']['timezone'],'-e','LANG=C.UTF-8','-e','LC_ALL=C.UTF-8','-e','LANGUAGE=en_US:en',
                  '-e','CPA_PROVIDER='+card['account_definition']['provider'],'-e','FIXTURE_OWNER='+card['owner'],'-e','ENVIRONMENT_ID='+card['environment_id'],
                  '-e','EXPECTED_RUNTIME='+json.dumps(card['runtime'],sort_keys=True),
                  '-e','PROXY_CONFIG_SHA256='+card['network_config_sha256'],'-e','OFFLINE_CENTRAL_REFRESH=1']
        if runtime:
            common += ['--security-opt','seccomp='+str(self.seccomp_path),'--network',card['network'],'--dns',self.fixture.get('ip','127.0.0.1'),
                       '--tmpfs','/run:rw,nosuid,nodev,noexec,size=8m,mode=755',
                       '--user','0:0','--cap-add','NET_ADMIN','--cap-add','SETUID','--cap-add','SETGID','--cap-add','SETPCAP','--cap-add','CHOWN','--cap-add','DAC_OVERRIDE','--cap-add','KILL',
                       '-e','NETWORK_STAGE=runtime']
        else:
            common += ['--network','none','--user','1001:1001','-e','NETWORK_STAGE=maintenance']
        return common

    def create(self, owner, proxy_url, progress=None):
        progress = progress or (lambda step: None)
        path = self.card(owner)
        if path.exists():
            raise ValueError('account_card_exists_no_reinitialize')
        progress('checking_socks')
        supplied = parse_proxy(proxy_url)
        account=self.registry.get(owner.lower());mode=self.fixture.get('mode','closed_test')
        fixture=self.fixture.get('accounts',{}).get(owner)
        ident=str(uuid.uuid4());name='socks-account-'+ident
        if mode in ('closed_test','closed_tls_test'):
            if not isinstance(fixture,dict):raise ValueError('fixture_account_unavailable')
            expected={'proxy_ip':self.fixture['ip'],'proxy_port':fixture['proxy_port'],'username':'test-'+owner,'password':'fixture-password-'+owner}
            if supplied!=expected:raise ValueError('test_proxy_required')
        if account['provider']=='mock-claude':
            if mode!='closed_test':raise ValueError('mock_provider_requires_closed_test')
            config={'test_only':True,'provider':'mock-claude','owner':owner,**supplied,'check_host':owner.lower()+'.upstream.invalid','check_port':8080,'expected_egress':fixture['egress']}
        elif account['provider']=='claude-subscription':
            if mode not in ('managed','closed_tls_test'):raise ValueError('provider_network_mode_mismatch')
            config={'test_only':False,'provider':'claude-subscription','owner':owner,**supplied,'check_mode':'https_exit','expected_egress':None}
        else:raise ValueError('provider_unavailable')
        # No account data volumes exist or are mounted during location discovery.
        probe_name='cpa-locale-'+uuid.uuid4().hex
        try:
            from creation_probe import discover, PROBE_SCRIPT
            location=discover([*DOCKER,'run','--rm','--name',probe_name,'-i','--network',self.fixture['network'],
                               '--read-only','--cap-drop','ALL','--cap-add','NET_ADMIN','--user','0:0',
                               '--security-opt','no-new-privileges','--entrypoint','python3',self.image,
                               '-B','-c',PROBE_SCRIPT],config,progress)
        finally:
            subprocess.run([*DOCKER,'rm','-f',probe_name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
        progress('reading_environment')
        runtime=json.loads(docker('run','--rm','--network','none','--user','1001:1001',
                                  '-e','NETWORK_STAGE=maintenance','-e','TZ='+location['timezone'],
                                  '--entrypoint','python3',self.image,'-B','/opt/native/retention_cli.py','inventory'))
        config.update(timezone=location['timezone'],language='en-US',expected_egress=location['exit_ip'])

        raw = json.dumps(config,sort_keys=True).encode()
        card = {'account_definition':{k:account[k] for k in ('slug','owner','provider')},'security_policy_sha256':self.seccomp_sha256,'owner':owner,'environment_id':ident,'image':self.image,'runtime':runtime,
                'location':location,'volume':name+'-state','backup':name+'-backup','network_config':name+'-network',
                'network_config_sha256':hashlib.sha256(raw).hexdigest(),'network':self.fixture['network'],'status':'creating'}
        write_json(path,card)
        progress('preparing_storage')
        for key in ('volume','backup','network_config'):
            docker('volume','create','--label','cpa.retention.id='+ident,card[key])
        progress('saving_network')
        command=[*DOCKER,'run','--rm','-i','--network','none','--user','1001:1001','--entrypoint','python3',
                 '--mount','type=volume,source='+card['network_config']+',target=/network-config',self.image,'-c',
                 "import sys,os,json;from pathlib import Path;os.umask(0o077);raw=sys.stdin.buffer.read();cfg=json.loads(raw);root=Path('/network-config');(root/'config.json').write_bytes(raw);(root/'timezone').write_text(cfg['timezone']+'\\n');(root/'localtime').write_bytes((Path('/usr/share/zoneinfo')/cfg['timezone']).read_bytes())"]
        subprocess.run(command,input=raw,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        progress('initializing_environment')
        self.helper(card,'initialize')
        progress('creating_container')
        card['container']=docker('create','--name',name,*self.args(card,runtime=True),self.image)
        card['status']='network_guarded_test'
        write_json(path,card)
        progress('starting_container')
        self.start(owner)
        progress('waiting_for_worker')
        self.wait_started(card)
        return card

    def wait_started(self, card, timeout=45):
        # Readiness checks only; never call a model or open the browser.
        import base64
        from creation_progress import CreationFailure
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            try:
                info=self.inspect(card)
                if not info['State']['Running']:raise CreationFailure('container_start_failed')
                if self.network_state(info)['healthy']:
                    result=subprocess.run([*DOCKER,'exec','--user','1001:1001','-i',card['container'],'/opt/native/worker','call'],
                                          input='{"path":"/health","body":{}}\n',text=True,capture_output=True,timeout=3)
                    if result.returncode==0:
                        frames=[json.loads(line) for line in result.stdout.splitlines()]
                        payload=b''.join(base64.b64decode(f['body'],validate=True) for f in frames if 'body' in f)
                        state=json.loads(payload)
                        if frames[0].get('status')==200 and frames[-1].get('done') and state.get('owner')==card['owner']:
                            return
            except CreationFailure:raise
            except (OSError,ValueError,KeyError,IndexError,subprocess.SubprocessError):pass
            time.sleep(.25)
        raise CreationFailure('container_readiness_failed')

    def load(self, owner):
        card=super().load(owner)
        account=self.registry.get(owner.lower())
        if card.get('account_definition')!={k:account[k] for k in ('slug','owner','provider')}:raise ValueError('account_definition_changed')
        if card.get('security_policy_sha256')!=self.seccomp_sha256:raise ValueError('saved_container_policy_changed')
        info=json.loads(docker('volume','inspect',card['network_config']))[0]
        if info['Driver']!='local' or info.get('Options') or info.get('Labels',{}).get('cpa.retention.id')!=card['environment_id']:
            raise ValueError('network_volume_mismatch')
        return card

    def inspect(self, card):
        info=json.loads(docker('inspect',card['container']))[0]
        mounts={m['Destination']:m for m in info['Mounts'] if m['Destination'] not in ('/tmp','/run')}
        expected={'/state':('volume',True),'/backup':('backup',True),'/network-config':('network_config',False)}
        config=info['HostConfig']
        options=config.get('SecurityOpt') or []
        policies=[json.loads(v.split('=',1)[1]) for v in options if v.startswith('seccomp=')]
        expected_caps={'NET_ADMIN','SETUID','SETGID','SETPCAP','CHOWN','DAC_OVERRIDE','KILL'}
        if (len(options)!=2 or policies!=[self.seccomp] or not any(v in ('no-new-privileges','no-new-privileges:true') for v in options)
            or {v.removeprefix('CAP_') for v in (config.get('CapAdd') or [])}!=expected_caps or config.get('CapDrop')!=['ALL']):raise ValueError('container_security_policy_mismatch')
        if info['Image']!=card['image'] or config['NetworkMode']!=card['network'] or config['Privileged'] or not config['ReadonlyRootfs'] or set(mounts)!=set(expected):
            raise ValueError('container_network_boundary_mismatch')
        for target,(key,writable) in expected.items():
            if mounts[target].get('Name')!=card[key] or mounts[target]['RW']!=writable:
                raise ValueError('container_volume_mismatch')
        if set(info['NetworkSettings']['Networks'])!={card['network']}:
            raise ValueError('extra_network_rejected')
        return info

    def network_state(self, info):
        script="import json,time;from pathlib import Path;p=Path('/run/network/live/status.json');d=json.loads(p.read_text()) if p.exists() else {};d['healthy']=bool(d.get('healthy') and 0<=time.time()-d.get('checked_at',0)<2);print(json.dumps(d))"
        state=json.loads(docker('exec','--user','1001:1001',info['Id'],'python3','-c',script,timeout=4))
        return {'fixed_timezone':state.get('fixed_timezone'),'observed_timezone':state.get('observed_timezone'),'timezone_warning':state.get('timezone_warning',False),'timezone_check_reason':state.get('timezone_check_reason'),'timezone_checked_at':state.get('timezone_checked_at'),'healthy':bool(state.get('healthy')),'reason':state.get('reason','network_initializing'),'check_mode':state.get('check_mode'),'network_checked_at':state.get('network_checked_at'),'periodic_network_checks':state.get('periodic_network_checks'),'warning':state.get('warning',False),'observation_healthy':state.get('observation_healthy'),'observation_reason':state.get('observation_reason'),'checking':state.get('checking',False),'last_success_at':state.get('last_success_at'),'next_check_in_seconds':state.get('next_check_in_seconds'),'active_connections':state.get('active_connections',0),'checked_at':state.get('checked_at')}

    def restore_new_volume(self, owner, snapshot):
        card=self.load(owner)
        if self.inspect(card)['State']['Running']:
            raise ValueError('stop_account_before_restore')
        fresh='socks-account-'+card['environment_id']+'-restore-'+uuid.uuid4().hex[:8]
        docker('volume','create','--label','cpa.retention.id='+card['environment_id'],fresh)
        self.helper(card,'restore',snapshot,state_volume=fresh)
        new=dict(card,volume=fresh)
        new['container']=docker('create',*self.args(new,runtime=True),self.image)
        new['previous']={'container':card['container'],'volume':card['volume']}
        write_json(self.card(owner),new)
        self.start(owner)
        return new


sys.path.insert(0,str(ROOT))

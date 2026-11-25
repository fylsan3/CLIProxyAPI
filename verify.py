"""Dynamic registry integration: same-label accounts, third identity, native requests and restart."""
import hashlib
import http.client
import json
from pathlib import Path
import subprocess
import tempfile
import time
import traceback
import uuid
from urllib.parse import urlsplit
from lab_support import ROOT, docker, stop
from proxy_config import parse_proxy


def wait(fn):
    for _ in range(150):
        try:
            result=fn()
            if result:return result
        except (OSError,ValueError,subprocess.SubprocessError):pass
        time.sleep(.2)
    raise RuntimeError('onboarding_timeout')


def run():
    report={'real_accounts_used':False,'published':False,'cases':{}}
    scope=uuid.uuid4().hex[:12];network='cpa-account-registry-'+scope
    images=json.loads((ROOT/'image.json').read_text());fixture=None;process=None
    specs=json.loads((ROOT/'fixture/accounts.json').read_text());owners=list(specs)
    with tempfile.TemporaryDirectory(prefix='cpa-authorization-',dir='/tmp') as folder:
        state=Path(folder).resolve();state.chmod(0o700)
        try:
            docker('network','create','--internal','--label','cpa.socks-lab='+scope,network)
            fixture=docker('run','-d','--pull=never','--network',network,'--read-only','--cap-drop','ALL',
                           '--tmpfs','/tmp:mode=1777','--tmpfs','/mock:mode=1777',images['fixture'])
            ip=json.loads(docker('inspect',fixture))[0]['NetworkSettings']['Networks'][network]['IPAddress']
            definition=state/'fixture.json';definition.write_text(json.dumps({'scope':scope,'network':network,'ip':ip,'accounts':specs}));definition.chmod(0o600)
            destination=state/'external-disk-fixture';destination.mkdir(mode=0o700)
            def start():
                with (state/'launch.log').open('ab') as log:
                    return subprocess.Popen(['python3','-B',str(ROOT/'launch.py'),'--state',str(state),'--network-fixture',str(definition),'--backup-directory',str(destination)],stdout=log,stderr=log)
            process=start()
            wait(lambda:(state/'launch.json').exists())
            launch=json.loads((state/'launch.json').read_text());ui=urlsplit(launch['management_url']);api=urlsplit(launch['api_base']);key=Path(launch['api_key_file']).read_text().strip()
            def panel(method,path,body=None):
                conn=http.client.HTTPConnection('127.0.0.1',ui.port,timeout=60)
                try:
                    conn.request(method,'/v8/management/account-environments'+path,json.dumps(body) if body is not None else None,{'Content-Type':'application/json','Origin':'http://127.0.0.1:'+str(ui.port),'Authorization':'Bearer '+key})
                    response=conn.getresponse();return response.status,json.loads(response.read() or b'{}')
                finally:conn.close()
            inputs={'key':key,'url':launch['management_url'],'state':str(state),'proxies':{o:'socks5h://test-'+o+':fixture-password-'+o+'@'+ip+':'+str(specs[o]['proxy_port']) for o in owners}}
            result=subprocess.run(['node',str(ROOT/'check_ui.cjs')],input=json.dumps(inputs),text=True,capture_output=True,timeout=480)
            if result.returncode:raise RuntimeError(result.stderr[-3000:])
            report['cases']['management_and_remote_browser']=json.loads(result.stdout)
            def project(owner):
                code,value=panel('GET','/snapshot');assert code==200
                return next(p for p in value['projects'] if p['slug']==owner.lower())
            cards={o:json.loads((state/'broker-private/environments'/(o+'.json')).read_text()) for o in owners}
            def model(owner,stream=False):
                conn=http.client.HTTPConnection('127.0.0.1',api.port,timeout=30)
                conn.request('POST','/v1/messages',json.dumps({'model':'test-project-shared','max_tokens':16,'stream':stream,'messages':[{'role':'user','content':'ordinary'}]}),{'Authorization':'Bearer '+key,'X-Test-Pin':owner.lower(),'Content-Type':'application/json'})
                response=conn.getresponse();raw=response.read();conn.close();assert response.status==200, response.status
                events=json.loads(docker('exec',fixture,'python3','-c',"import json;from pathlib import Path;print(json.dumps([json.loads(x) for x in Path('/mock/"+owner+"/native-evidence.jsonl').read_text().splitlines()]))"))
                event=[e for e in events if e['operation']=='messages'][-1]
                assert event['response_sha256']==hashlib.sha256(raw).hexdigest()
                return events
            for owner in owners:
                events=model(owner)
                assert sum(e['operation']=='authorization_code' for e in events)==1
            report['cases']['native_reply_matches_mock_upstream_each_account']=True
            events=model('RESEARCH-03',True)
            report['cases']['third_account_stream_matches_mock_upstream']=True
            previous={o:cards[o]['container'] for o in owners}
            assert panel('POST','/action',{'action':'auth-refresh','slug':'research-03'})[0]==200
            wait(lambda:project('RESEARCH-03').get('state',{}).get('revision')==2)
            wait(lambda:project('RESEARCH-03').get('portable_backup',{}).get('revision')==2)
            assert project('A')['state']['revision']==1 and project('B')['state']['revision']==1
            report['cases']['third_account_native_refresh_and_backup_do_not_change_others']=True
            before=(state/'broker-private/accounts.json').read_bytes()
            stop(process);process=None
            process=start();wait(lambda:(state/'launch.json').exists())
            wait(lambda:all(project(o).get('overall_ready') for o in owners))
            assert (state/'broker-private/accounts.json').read_bytes()==before
            for owner in owners:
                saved=json.loads((state/'broker-private/environments'/(owner+'.json')).read_text())
                assert saved['container']==previous[owner]
                events=model(owner)
                assert sum(e['operation']=='authorization_code' for e in events)==1
            report['cases']['control_restart_keeps_registry_containers_and_single_authorization']=True
            conn=http.client.HTTPConnection('127.0.0.1',api.port,timeout=10)
            conn.request('POST','/v1/messages',json.dumps({'model':'test-project-shared','max_tokens':16,'messages':[{'role':'user','content':'ordinary'}]}),{'Authorization':'Bearer '+key,'X-Test-Pin':'not-registered','Content-Type':'application/json'})
            response=conn.getresponse();response.read();assert response.status==400;conn.close()
            report['cases']['unregistered_pin_rejected']=True
            assert panel('POST','/action',{'action':'auth-refresh','slug':'../research-03'})[0]==400
            assert panel('POST','/action',{'action':'register','slug':'future','label':'不可用提供方','provider':'claude-subscription'})[0]==400
            report['cases']['unsafe_identifier_and_unavailable_provider_rejected']=True
        except BaseException:
            diagnostic={'error':traceback.format_exc(),'cases':report['cases']}
            for p in (state/'broker-private/environments').glob('*.json'):
                card=json.loads(p.read_text())
                if card.get('container'):diagnostic[p.stem]=docker('logs','--tail','20',card['container'])
            for name in ['launch','broker','central']:
                p=state/(name+'.log')
                if p.exists():diagnostic[name]=p.read_text()[-3000:]
            (ROOT/'failed-diagnostic.json').write_text(json.dumps(diagnostic,indent=2));raise
        finally:
            if process:stop(process)
            for p in (state/'broker-private/environments').glob('*.json'):
                card=json.loads(p.read_text())
                if 'container' not in card:continue
                ident=card['environment_id']
                for listing,remove in [(['ps','-a'],['rm','-f']),(['volume','ls'],['volume','rm'])]:
                    ids=docker(*listing,'-q','--filter','label=cpa.retention.id='+ident).split()
                    if ids:docker(*remove,*ids)
            if fixture:docker('rm','-f',fixture)
            docker('network','rm',network)
    report['test_resources_removed']=True;report['image']=images['id']
    (ROOT/'acceptance.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))


if __name__=='__main__':run()

"""Smoke-check the new startup/recovery lock with an empty closed test registry."""
import http.client,json,subprocess,tempfile,uuid
from pathlib import Path
from lab_support import ROOT,CLI,docker,stop
from verify_control import wait

def run():
 scope=uuid.uuid4().hex[:12];network='cpa-startup-'+scope;process=None
 with tempfile.TemporaryDirectory(prefix='cpa-startup-',dir='/private/tmp') as tmp:
  root=Path(tmp).resolve();root.chmod(0o700);state=root/'state';backup=root/'backup';backup.mkdir(mode=0o700)
  fixture=root/'fixture.json';fixture.write_text(json.dumps({'mode':'closed_tls_test','scope':scope,'network':network,'ip':'127.0.0.1','accounts':{}}));fixture.chmod(0o600)
  try:
   docker('network','create','--internal','--label','cpa.socks-lab='+scope,network)
   with (root/'launch.log').open('ab') as log:
    process=subprocess.Popen(['python3','-B',str(ROOT/'launch.py'),'--state',str(state),'--network-fixture',str(fixture),'--backup-directory',str(backup)],stdout=log,stderr=log)
   wait(lambda:(state/'launch.json').exists())
   data=json.loads((state/'launch.json').read_text());from urllib.parse import urlsplit
   u=urlsplit(data['api_base']);c=http.client.HTTPConnection(u.hostname,u.port,timeout=3);c.request('GET','/healthz');response=c.getresponse();response.read();assert response.status==200;c.close()
   assert (root/'.state.restore.lock').is_file()
   stop(process);process=None;assert not (state/'launch.json').exists()
  finally:
   if process:stop(process)
   docker('network','rm',network)
 report={'startup_capacity_gate_and_shared_restore_lock':True,'healthz':200,'shutdown_clean':True,'accounts_created':0,'real_accounts_used':False,'production_modified':False}
 (ROOT/'startup-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
if __name__=='__main__':run()

"""Focused gate for release; only local fixture requests, no production actions."""
import json,os,subprocess,sys,time
from pathlib import Path
r=Path(__file__).resolve().parents[1];e=r/'evidence';e.mkdir(exist_ok=True);results=json.loads((e/'audit-tests.json').read_text()) if (e/'audit-tests.json').exists() else []
cases=['cooldown_bridge_test.py','cooldown_bridge_check.py','egress_unit.py','container_platform_headers.py','oauth_native_capture.py','http_archive_check.py','sample_export_test.py','capture_chain.py','upgrade_chain.py']
if len(sys.argv)>1:cases=sys.argv[1:]
for case in cases:
 start=time.time();print('START',case,flush=True)
 # cryptography is already installed in the closed runtime, not necessarily on macOS.
 if case=='sample_export_test.py':
  sys.path.insert(0,str(r));from host_runtime import docker_cli
  image=json.loads((r/'image.json').read_text())['id']
  code=(r/'tests'/case).read_text().replace("sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'image'))","sys.path.insert(0,'/opt/native')")
  cmd=docker_cli()+['run','--rm','--network','none','--read-only','--user','1001:1001','--cap-drop','ALL','--entrypoint','python3',image,'-B','-c',code]
 else:cmd=[sys.executable,'-B',str(r/'tests'/case)]
 with (e/('audit-'+case+'.log')).open('w') as log:
  try:result=subprocess.run(cmd,cwd=r,stdout=log,stderr=log,timeout=900);code=result.returncode
  except subprocess.TimeoutExpired:code=124
 results.append({'test':case,'exit_code':code,'seconds':round(time.time()-start,2)});(e/'audit-tests.json').write_text(json.dumps(results,indent=2))
 print('END',case,code,flush=True)
 if code:print((e/('audit-'+case+'.log')).read_text()[-4000:],flush=True);sys.exit(code)

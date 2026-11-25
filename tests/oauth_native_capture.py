"""Run the real worker transport and native CPA OAuth functions on loopback only."""
import json,os,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(R))
from build_inputs import verify_source
from build import check_overrides
from host_runtime import docker_cli
verify_source(R);check_overrides()
T=Path(os.environ['CPA_BUILD_TOOLS']);S=R/'source'
with tempfile.TemporaryDirectory(prefix='cpa-oauth-capture-') as folder:
 p=Path(folder);mapping=json.loads((R/'overlay-inputs.json').read_text())
 replacements={str(S/k):str(R/v) for k,v in mapping.items()}
 virtual=S/'cmd/server/oauth_native_capture_test.go';replacements[str(virtual)]=str(R/'tests/oauth_native_capture_test.go')
 overlay=p/'overlay.json';overlay.write_text(json.dumps({'Replace':replacements}))
 files=[str(S/k) for k in mapping if k.startswith('cmd/server/offline_') and k.endswith('.go')]
 env=dict(os.environ,GOROOT=str(T/'go'),GOMODCACHE=str(T/'modules'),GOCACHE='/tmp/cpa-linux-candidate-cache',GOOS='linux',GOARCH='arm64',CGO_ENABLED='0',GOTOOLCHAIN='local',GOENV='off',GOPROXY='off',GOSUMDB='off',GOWORK='off',GOFLAGS='')
 subprocess.run([str(T/'go/bin/go'),'test','-c','-mod=readonly','-p','2','-tags','cpa_offline','-overlay',str(overlay),'-o',str(p/'capture'),*files,str(virtual)],cwd=S,env=env,check=True)
 script="""import sys,subprocess,json
from pathlib import Path
p=Path('/tmp/capture');p.write_bytes(sys.stdin.buffer.read());p.chmod(0o700)
r=subprocess.run([str(p),'-test.v','-test.timeout=45s'],capture_output=True,text=True)
print(r.stdout+r.stderr,file=sys.stderr)
if r.returncode:sys.exit(r.returncode)
print(Path('/tmp/oauth-native-capture.json').read_text())
"""
 image=json.loads((R/'image.json').read_text())['id']
 result=subprocess.run(docker_cli()+['run','--rm','-i','--network','none','--user','1001:1001','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--tmpfs','/tmp:rw,exec,nosuid,nodev,size=128m,mode=1777','--entrypoint','python3',image,'-B','-c',script],input=(p/'capture').read_bytes(),capture_output=True,timeout=60)
 print(result.stderr.decode());result.check_returncode()
 data=json.loads(result.stdout);(R/'evidence/oauth-native-final-wire.json').write_text(json.dumps(data,indent=2)+'\n');(R/'evidence/oauth-native-test.txt').write_bytes(result.stderr)
 print(json.dumps({'oauth_requests':len(data['oauth_requests']),'oauth_native_and_final_identical':data['oauth_native_and_final_identical'],'final_model_requests':len(data['final_model_requests']),'native_fallback':data['native_model_fallback'][0]['headers'].get('User-Agent'),'production_changed':False}))

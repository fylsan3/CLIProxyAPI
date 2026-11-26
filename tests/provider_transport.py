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
 virtual=S/'cmd/server/provider_transport_test.go';replacements[str(virtual)]=str(R/'tests/provider_transport_test.go')
 overlay=p/'overlay.json';overlay.write_text(json.dumps({'Replace':replacements}))
 files=[str(S/k) for k in mapping if k.startswith('cmd/server/offline_') and k.endswith('.go')]
 env=dict(os.environ,GOROOT=str(T/'go'),GOMODCACHE=str(T/'modules'),GOCACHE='/tmp/cpa-linux-candidate-cache',GOOS='linux',GOARCH='arm64',CGO_ENABLED='0',GOTOOLCHAIN='local',GOENV='off',GOPROXY='off',GOSUMDB='off',GOWORK='off',GOFLAGS='')
 subprocess.run([str(T/'go/bin/go'),'test','-c','-mod=readonly','-p','2','-tags','cpa_offline','-overlay',str(overlay),'-o',str(p/'capture'),*files,str(virtual)],cwd=S,env=env,check=True)
 script="""import sys,subprocess
from pathlib import Path
p=Path('/tmp/capture');p.write_bytes(sys.stdin.buffer.read());p.chmod(0o700)
r=subprocess.run([str(p),'-test.v','-test.timeout=45s'],capture_output=True,text=True)
print(r.stdout+r.stderr)
sys.exit(r.returncode)
"""
 image=json.loads((R/'image.json').read_text())['id']
 result=subprocess.run(docker_cli()+['run','--rm','-i','--network','none','--user','1001:1001','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--tmpfs','/tmp:rw,exec,nosuid,nodev,size=128m,mode=1777','--entrypoint','python3',image,'-B','-c',script],input=(p/'capture').read_bytes(),capture_output=True,timeout=60)
 print(result.stdout.decode()+result.stderr.decode());(R/'evidence/provider-transport.txt').write_bytes(result.stdout+result.stderr);result.check_returncode()

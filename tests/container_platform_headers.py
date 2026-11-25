"""Compile the exact production header functions and capture their local HTTP output.
The short-lived test container has no external network or account mounts.
"""
import hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(R))
from host_runtime import docker_cli
from build import check_overrides
check_overrides()
source=(R/'src/cmd/server/offline_worker_entry.go').read_text()
functions=source[source.index('func containerPlatformHeaders('):source.index('\ntype providerHeadersKey')]
reference=(R/'manual-header-reference.go.txt').read_text()
baseline=reference[reference.index('func applyProviderHeaders('):reference.index('\ntype providerHeadersKey')].replace('func applyProviderHeaders(', 'func applyManualBaseline(',1)
tool=Path(os.environ.get('CPA_BUILD_TOOLS',str(R/'.build-tools'))).resolve()
with tempfile.TemporaryDirectory(prefix='cpa-platform-') as folder:
 p=Path(folder);(p/'go.mod').write_text('module platformcheck\n\ngo 1.26\n')
 (p/'headers.go').write_text('package main\nimport("net/http";"strings";"syscall")\n'+functions+'\n'+baseline)
 (p/'headers_test.go').write_text((R/'tests/container_platform_headers_test.go').read_text())
 env=dict(os.environ,GOROOT=str(tool/'go'),GOOS='linux',GOARCH='arm64',CGO_ENABLED='0',GOENV='off',GOTOOLCHAIN='local',GOPROXY='off',GOSUMDB='off',GOFLAGS='',GOWORK='off',GOCACHE='/tmp/cpa-platform-go-cache')
 subprocess.run([str(tool/'go/bin/go'),'test','-c','-o',str(p/'check')],cwd=p,env=env,check=True)
 image=json.loads((R/'image.json').read_text())['id']
 bootstrap="import os,sys;from pathlib import Path;p=Path('/tmp/check');p.write_bytes(sys.stdin.buffer.read());p.chmod(0o700);os.execv(str(p),[str(p),'-test.v'])"
 result=subprocess.run(docker_cli()+['run','--rm','-i','--pull=never','--network','none','--read-only','--user','1001:1001','--cap-drop','ALL','--security-opt','no-new-privileges','--tmpfs','/tmp:rw,exec,nosuid,nodev,size=64m,mode=1777','--entrypoint','python3',image,'-c',bootstrap],input=(p/'check').read_bytes(),capture_output=True,timeout=45)
 print(result.stdout.decode());print(result.stderr.decode(),file=sys.stderr);result.check_returncode()
 (R/'evidence/container-platform-headers.txt').write_bytes(result.stdout)
 print(json.dumps({'worker_source_sha256':hashlib.sha256(source.encode()).hexdigest(),'test':'exact production header functions, local wire capture','real_accounts_used':False,'production_changed':False}))

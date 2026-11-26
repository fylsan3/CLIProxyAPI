"""Compile production Go network/policy modules; execute only in a network-none container."""
import os,json,subprocess,tempfile,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(ROOT));from host_runtime import docker_cli
TOOL=Path(os.environ['CPA_BUILD_TOOLS'])
with tempfile.TemporaryDirectory(prefix='cpa-egress-unit-') as d:
 p=Path(d)
 (p/'internal/accountheaders').mkdir(parents=True)
 (p/'internal/accountheaders/policy.go').write_bytes((ROOT/'src/internal/accountheaders/policy.go').read_bytes())

 for name in ('go.mod','go.sum'):(p/name).write_bytes((ROOT/'source'/name).read_bytes())
 for name in ('offline_network.go','offline_header_policy.go'):(p/name).write_text((ROOT/'src/cmd/server'/name).read_text().replace('//go:build cpa_offline',''))
 (p/'egress_test.go').write_bytes((ROOT/'tests/egress_unit_test.go').read_bytes())
 env=dict(os.environ,GOROOT=str(TOOL/'go'),GOMODCACHE=str(TOOL/'modules'),GOCACHE='/tmp/cpa-linux-candidate-cache',GOOS='linux',GOARCH='arm64',CGO_ENABLED='0',GOTOOLCHAIN='local',GOENV='off',GOPROXY='off',GOSUMDB='off',GOWORK='off',GOFLAGS='')
 subprocess.run([str(TOOL/'go/bin/go'),'test','-mod=readonly','-c','-o',str(p/'tests')],cwd=p,env=env,check=True)
 script="import sys,os;from pathlib import Path;p=Path('/tmp/tests');p.write_bytes(sys.stdin.buffer.read());p.chmod(0o755);os.execv(str(p),[str(p),'-test.v','-test.timeout=30s'])"
 image=json.loads((ROOT/'image.json').read_text())['id'];r=subprocess.run(docker_cli()+['run','--rm','-i','--network','none','--user','1001:1001','--read-only','--cap-drop','ALL','--tmpfs','/tmp:rw,exec,size=64m,mode=1777','--entrypoint','python3',image,'-c',script],input=(p/'tests').read_bytes(),capture_output=True,timeout=45)
 print(r.stdout.decode());print(r.stderr.decode());r.check_returncode()
 (ROOT/'evidence/egress-unit.txt').write_bytes(r.stdout)

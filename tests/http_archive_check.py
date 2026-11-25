"""Test production capture functions with an actual HTTP transport, then replay offline."""
import io,json,os,subprocess,sys,tarfile,tempfile
from pathlib import Path
R=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(R))
from host_runtime import docker_cli
T=Path(os.environ['CPA_BUILD_TOOLS'])
with tempfile.TemporaryDirectory(prefix='cpa-archive-test-') as tmp:
 p=Path(tmp);(p/'go.mod').write_text('module archivecheck\n\ngo 1.26\n')
 (p/'archive.go').write_text((R/'src/cmd/server/offline_http_archive.go').read_text().replace('//go:build cpa_offline',''))
 source=(R/'src/cmd/server/offline_worker_entry.go').read_text();helpers=source[source.index('func safeFile('):source.index('func saveRecord(')]
 (p/'storage.go').write_text('package main\nimport("os";"syscall";"errors";"path/filepath")\n'+helpers)
 (p/'archive_test.go').write_text((R/'tests/http_archive_test.go').read_text())
 export=p/'export'
 env=dict(os.environ,GOROOT=str(T/'go'),GOCACHE='/tmp/cpa-archive-go-cache',GOPROXY='off',GOTOOLCHAIN='local',GOENV='off',ARCHIVE_TEST_EXPORT=str(export))
 subprocess.run([str(T/'go/bin/go'),'test','-race','-count=1','-v','.'],env=env,cwd=p,check=True)
 sample=next((export/'http-samples').iterdir());exchange=sample/'0001'
 data=io.BytesIO()
 with tarfile.open(fileobj=data,mode='w') as tar:
  for f in export.rglob('*'):
   if f.is_file():tar.add(f,arcname=str(f.relative_to(export)))
 bootstrap="""import io,tarfile,sys,json,os
from pathlib import Path
sys.path.insert(0,'/opt/native');import http_archive
root=Path('/tmp/archives');root.mkdir(mode=0o700)
with tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read())) as tar:tar.extractall(root,filter='data')
key=http_archive.private_file(root/'http-capture.key');folder=next((root/'http-samples').iterdir())/'0001'
result=http_archive.replay(folder,key)
# Tampering and truncation must fail rather than produce an apparently valid sample.
p=folder/'response.bin.enc';original=p.read_bytes();p.write_bytes(original[:-10])
try:http_archive.load_exchange(folder,key)
except Exception:result['truncation_rejected']=True
else:raise AssertionError('truncation accepted')
p.write_bytes(original[:-1]+bytes([original[-1]^1]))
try:http_archive.load_exchange(folder,key)
except Exception:result['tamper_rejected']=True
else:raise AssertionError('tamper accepted')
print(json.dumps(result,indent=2))
"""
 image=json.loads((R/'image.json').read_text())['id']
 result=subprocess.run(docker_cli()+['run','--rm','--pull=never','--network','none','--read-only','--user','1001:1001','--cap-drop','ALL','--tmpfs','/tmp:rw,nosuid,nodev,size=32m,mode=1777','-i','--entrypoint','python3',image,'-c',bootstrap],input=data.getvalue(),capture_output=True,timeout=40)
 print(result.stdout.decode());print(result.stderr.decode(),file=sys.stderr);result.check_returncode()
 (R/'evidence/http-archive-unit-replay.json').write_bytes(result.stdout)

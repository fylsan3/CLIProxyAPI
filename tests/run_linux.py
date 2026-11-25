import hashlib,json,subprocess,sys
from pathlib import Path
r=Path(__file__).resolve().parent.parent;sys.path.insert(0,str(r));from host_runtime import docker_cli
image=json.loads((r/'image.json').read_text())['id']
files={'network_guard.py':(r/'linux/network_guard.py').read_bytes(),'linux_probe.py':(r/'tests/linux_probe.py').read_bytes(),'central':(r/'central/cli-proxy-api-linux-arm64').read_bytes()}
bootstrap='''import hashlib,json,os,sys
from pathlib import Path
items=json.loads(sys.stdin.buffer.readline())
for item in items:
 raw=sys.stdin.buffer.read(item['size'])
 if len(raw)!=item['size'] or hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('input_corrupt')
 p=Path('/tmp')/item['name'];p.write_bytes(raw);p.chmod(0o755)
os.execv('/usr/bin/python3',['python3','-B','/tmp/linux_probe.py'])
'''
p=subprocess.Popen(docker_cli()+['run','--rm','-i','--pull=never','--network','none','--read-only','--cap-drop','ALL','--cap-add','DAC_OVERRIDE','--cap-add','KILL','--cap-add','CHOWN','--cap-add','SETUID','--cap-add','SETGID','--security-opt','no-new-privileges','--security-opt','seccomp=unconfined','--tmpfs','/tmp:rw,exec,nosuid,nodev,size=512m,mode=1777','--entrypoint','python3',image,'-B','-c',bootstrap],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
try:
 meta=[dict(name=n,size=len(b),sha256=hashlib.sha256(b).hexdigest()) for n,b in files.items()]
 p.stdin.write(json.dumps(meta).encode()+b'\n')
 for raw in files.values():p.stdin.write(raw)
 p.stdin.close();p.stdin=None;out,err=p.communicate(timeout=80)
finally:
 if p.poll() is None:p.kill();p.wait()
report={'exit':p.returncode,'stdout':out.decode(),'stderr':err.decode(),'test_kind':'Linux container, not target systemd host'}
(r/'evidence/linux-test.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2));raise SystemExit(p.returncode)

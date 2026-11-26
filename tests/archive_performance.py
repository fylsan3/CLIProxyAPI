"""Measure existing capture functions; fake bytes, loopback only, disposable disk.

Runs Mac on host disk and Linux ARM64 on a NEW Docker volume. Never mounts an
account directory. This is a boundary benchmark, not end-to-end capacity testing.
"""
import json, os, subprocess, sys, tempfile, uuid
from pathlib import Path

R=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(R))
from host_runtime import docker_cli
T=Path(os.environ['CPA_BUILD_TOOLS'])

def result(command, **kwargs):
    run=subprocess.run(command,capture_output=True,text=True,timeout=300,**kwargs)
    if run.returncode:
        print(run.stdout);print(run.stderr,file=sys.stderr);run.check_returncode()
    for line in run.stdout.splitlines():
        if line.startswith('BENCH_RESULT='):
            return json.loads(line.removeprefix('BENCH_RESULT='))
    raise RuntimeError('missing result: '+run.stdout)

with tempfile.TemporaryDirectory(prefix='cpa-archive-perf-') as tmp:
    p=Path(tmp);(p/'go.mod').write_text('module github.com/router-for-me/CLIProxyAPI/v8\n\ngo 1.26\n')
    (p/'internal/accountheaders').mkdir(parents=True)
    (p/'internal/accountheaders/policy.go').write_bytes((R/'src/internal/accountheaders/policy.go').read_bytes())
    for target,source in [('archive.go','offline_http_archive.go'),('session.go','offline_capture_session.go'),('policy.go','offline_header_policy.go')]:
        (p/target).write_text((R/'src/cmd/server'/source).read_text().replace('//go:build cpa_offline',''))
    with (p/'policy.go').open('a') as f:
        f.write('\nfunc containerPlatformHeaders()(string,string){return "Linux","arm64"}\n')
    source=(R/'src/cmd/server/offline_worker_entry.go').read_text()
    (p/'storage.go').write_text('package main\nimport("os";"syscall";"errors";"path/filepath")\n'+source[source.index('func safeFile('):source.index('func saveRecord(')])
    (p/'performance_test.go').write_bytes((R/'tests/archive_performance_test.go').read_bytes())
    env=dict(os.environ,GOROOT=str(T/'go'),GOCACHE='/tmp/cpa-archive-go-cache',GOPROXY='off',GOTOOLCHAIN='local',GOENV='off',GOMAXPROCS='2')
    (p/'mac-data').mkdir()
    print('Mac capture-boundary benchmark',flush=True)
    mac=result([str(T/'go/bin/go'),'test','-count=1','-timeout=5m','-run=^TestArchivePerformance$','-v','.'],cwd=p,env=dict(env,BENCH_DIR=str(p/'mac-data')))
    mac['storage']='Mac host temporary directory on disk; GOMAXPROCS=2; no CPU quota'
    output=R/'evidence/archive-performance.json';output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps({'mac':mac},indent=2)+'\n')
    subprocess.run([str(T/'go/bin/go'),'test','-c','-o',str(p/'benchmark-linux')],cwd=p,env=dict(env,GOOS='linux',GOARCH='arm64',CGO_ENABLED='0'),check=True,timeout=180)
    cli=docker_cli();volume='cpa-audit3-perf-'+uuid.uuid4().hex[:12];container=volume+'-runner'
    subprocess.run(cli+['volume','create','--label','cpa.test=archive-performance',volume],check=True,capture_output=True)
    try:
        print('Linux capture-boundary benchmark (new disposable volume)',flush=True)
        image=json.loads((R/'image.json').read_text())['id']
        subprocess.run(cli+['create','--name',container,'--pull=never','--network','none','--read-only','--cap-drop','ALL','--memory','512m','--cpus','2','--mount',f'type=volume,source={volume},target=/data','--tmpfs','/tmp:rw,nosuid,nodev,size=32m,mode=1777','-e','BENCH_DIR=/data','-e','GOMAXPROCS=2','--user','0:0','--entrypoint','/data/benchmark',image,'-test.run=^TestArchivePerformance$','-test.v','-test.timeout=5m'],check=True,capture_output=True)
        subprocess.run(cli+['cp',str(p/'benchmark-linux'),container+':/data/benchmark'],check=True,capture_output=True)
        linux=result(cli+['start','-a',container])
        linux['storage']='new Docker named volume on Mac Colima Linux VM; not tmpfs; 2 CPU quota, 512MiB limit; not physical Linux server'
    finally:
        subprocess.run(cli+['rm','-f',container],capture_output=True)
        subprocess.run(cli+['volume','rm',volume],check=True,capture_output=True)
    report={'mac':mac,'linux_container':linux}
    output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

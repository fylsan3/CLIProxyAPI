"""Unified build subcommand: preserve Go worker, pin CLI, build central API and UI."""
import io,json,os,shutil,subprocess,tarfile
from pathlib import Path

def build_claude_code(binary,runtime_base):
    from build import ROOT,SOURCE,TOOL,digest,run,check_overrides
    from build_inputs import remind_linked_review,verify_source
    from host_runtime import docker_cli
    if not runtime_base:raise ValueError('explicit_test_runtime_base_required')
    remind_linked_review(ROOT,'build:claude-code');verify_source(ROOT);check_overrides()
    lock=json.loads((ROOT/'claude-code-lock.json').read_text());binary=Path(binary).resolve()
    if digest(binary)!=lock['binary_sha256'] or binary.stat().st_size!=lock['binary_bytes']:raise ValueError('claude_binary_not_pinned')
    out=ROOT/'evidence/claude-code-build';out.mkdir(parents=True,exist_ok=True)
    mapping=json.loads((ROOT/'overlay-inputs.json').read_text())
    overlay=out/'overlay.json';overlay.write_text(json.dumps({'Replace':{str(SOURCE/k):str(ROOT/v) for k,v in mapping.items()}}))
    run([str(TOOL/'go/bin/gofmt'),'-w',str(ROOT/'src/internal/api/server_routes.go'),str(ROOT/'src/internal/api/handlers/management/account_console.go')])
    env=dict(os.environ,GOROOT=str(TOOL/'go'),GOMODCACHE=str(TOOL/'modules'),GOCACHE='/private/tmp/cpa-linux-candidate-cache',GOARCH='arm64',CGO_ENABLED='0',GOTOOLCHAIN='local',GOENV='off',GOPROXY='off',GOSUMDB='off',GOFLAGS='',GOWORK='off')
    for system in ('darwin','linux'):
        env['GOOS']=system
        run([str(TOOL/'go/bin/go'),'build','-mod=readonly','-p','2','-overlay',str(overlay),'-ldflags','-X main.Version=8.1.1-claude-code-2.1.331','-o',str(out/('central-'+system)),'./cmd/server'],env,SOURCE)
        print('Built Claude Code central API for '+system,flush=True)
    run([os.sys.executable,'-B',str(ROOT/'build_page.py')])
    cli=docker_cli();run(cli+['image','inspect',runtime_base])
    image='cpa-claude-code:2.1.331-candidate'
    files={'claude':binary,'claude_code.py':ROOT/'image/claude_code.py','claude_shared_auth.py':ROOT/'image/claude_shared_auth.py','claude_open_browser.py':ROOT/'image/claude_open_browser.py','entry.py':ROOT/'image/entry.py','browser_worker.py':ROOT/'image/browser_worker.py'}
    dockerfile='FROM '+runtime_base+'\nCOPY claude /opt/claude-code/claude\nCOPY claude_code.py claude_shared_auth.py claude_open_browser.py entry.py /opt/native/\nCOPY browser_worker.py /opt/sample/worker.py\n'
    with (out/'docker-build.log').open('wb') as log:
        p=subprocess.Popen(cli+['build','--network','none','--pull=false','-t',image,'-'],stdin=subprocess.PIPE,stdout=log,stderr=log)
        with tarfile.open(fileobj=p.stdin,mode='w|') as tar:
            data=dockerfile.encode();i=tarfile.TarInfo('Dockerfile');i.size=len(data);tar.addfile(i,io.BytesIO(data))
            for name,path in files.items():
                info=tar.gettarinfo(str(path),arcname=name)
                if name in ('claude','claude_open_browser.py'):info.mode=0o755
                with path.open('rb') as source:tar.addfile(info,source)
        p.stdin.close()
        if p.wait():raise ValueError('claude_image_build_failed')
    image_id=json.loads(run(cli+['image','inspect',image]))[0]['Id']
    worker=run(cli+['run','--rm','--network','none','--entrypoint','sha256sum',image_id,'/opt/native/worker']).split()[0]
    base_worker=run(cli+['run','--rm','--network','none','--entrypoint','sha256sum',runtime_base,'/opt/native/worker']).split()[0]
    if worker!=base_worker:raise ValueError('go_worker_changed')
    observed=run(cli+['run','--rm','--network','none','--read-only','--tmpfs','/tmp:rw,mode=1777','--entrypoint','/opt/claude-code/claude',image_id,'--version']).strip()
    if not observed.startswith(lock['version']+' '):raise ValueError('claude_version_mismatch')
    manifest={'version_observed_at_build':observed,'schema':1,'image':image,'image_id':image_id,'runtime_base':runtime_base,'claude':lock,'worker_sha256':worker,'central':{s:digest(out/('central-'+s)) for s in ('darwin','linux')},'image_inputs':{name:digest(path) for name,path in files.items()},'production_changed':False,'go_worker_rebuilt':False,'headers_and_cc_version_changed':False}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    from package_claude_code import package
    package()
    print('Claude Code candidate built; no production deployment. '+str(out),flush=True)

import json,os,subprocess
from pathlib import Path
r=Path(__file__).resolve().parent;source=r/'source';tool=r.parent/'cpa-security-audit/lab/replay80';test=source/'cmd/server/offline_header_test.go';overlay=json.loads((r/'overlay.json').read_text());overlay['Replace'][str(test)]=str(r/'provider_transport_test.go');path=r/'header-test-overlay.json';path.write_text(json.dumps(overlay))
env=dict(os.environ,GOROOT=str(tool/'go'),GOMODCACHE=str(tool/'modules'),GOCACHE='/private/tmp/cpa-linux-candidate-cache',GOOS='darwin',GOARCH='arm64',CGO_ENABLED='1',GOTOOLCHAIN='local',GOENV='off',GOPROXY='off')
subprocess.run([str(tool/'go/bin/gofmt'),'-w',str(r/'provider_transport_test.go')],check=True)
p=subprocess.run([str(tool/'go/bin/go'),'test','-race','-mod=readonly','-tags','cpa_offline','-overlay',str(path),'-run','TestContainerHeaderBoundary|TestConcurrentHeaderCaptureAndRawError','-v',str(source/'cmd/server/offline_worker_entry.go'),str(source/'cmd/server/offline_refresh_controller.go'),str(test)],cwd=source,env=env,text=True,capture_output=True)
(r/'header-go-test-result.txt').write_text(p.stdout+p.stderr);print(p.stdout+p.stderr);raise SystemExit(p.returncode)

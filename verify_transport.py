"""Run transport tests only against in-process local servers."""
import json,os,subprocess
from pathlib import Path
r=Path(__file__).resolve().parent;s=r/'source';t=r.parent/'cpa-security-audit/lab/replay80'
subprocess.run([str(t/'go/bin/gofmt'),'-w',str(r/'provider_transport_test.go')],check=True)
overlay=json.loads((r/'overlay.json').read_text());test=s/'cmd/server/container_provider_test.go';overlay['Replace'][str(test)]=str(r/'provider_transport_test.go');(r/'test-overlay.json').write_text(json.dumps(overlay))
env=dict(os.environ,GOROOT=str(t/'go'),GOMODCACHE=str(t/'modules'),GOCACHE='/private/tmp/cpa-linux-candidate-cache',GOOS='darwin',GOARCH='arm64',CGO_ENABLED='0',GOTOOLCHAIN='local',GOENV='off',GOPROXY='off')
p=subprocess.run([str(t/'go/bin/go'),'test','-v','-mod=readonly','-tags','cpa_offline','-overlay',str(r/'test-overlay.json'),str(s/'cmd/server/offline_worker_entry.go'),str(s/'cmd/server/offline_refresh_controller.go'),str(test)],cwd=s,env=env,text=True,capture_output=True)
(r/'transport-unit-result.txt').write_text(p.stdout+p.stderr);print(p.stdout+p.stderr);raise SystemExit(p.returncode)

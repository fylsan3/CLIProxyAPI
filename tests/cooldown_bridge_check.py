import os,subprocess,tempfile,shutil
from pathlib import Path
r=Path(__file__).resolve().parents[1];t=Path(os.environ['CPA_BUILD_TOOLS'])
with tempfile.TemporaryDirectory(prefix='cpa-cooldown-') as folder:
 p=Path(folder);(p/'go.mod').write_text('module cooldowncheck\n\ngo 1.26\n')
 for name in ('container_cooldown.go','container_http_headers.go'):shutil.copy2(r/'src/internal/util'/name,p/name)
 shutil.copy2(r/'tests/cooldown_bridge_test.go',p/'cooldown_test.go')
 env=dict(os.environ,GOROOT=str(t/'go'),GOCACHE='/tmp/cpa-cooldown-cache',GOPROXY='off',GOTOOLCHAIN='local',GOENV='off')
 subprocess.run([str(t/'go/bin/go'),'test','-race','-v','.'],env=env,cwd=p,check=True)

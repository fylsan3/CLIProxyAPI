"""Stage a self-contained candidate without changing production or root release files."""
import hashlib,json,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def package():
    out=ROOT/'evidence/claude-code-build';build=json.loads((out/'manifest.json').read_text())
    stage=out/'package';stage.mkdir(exist_ok=True)
    selected=list(ROOT.glob('*.py'))
    selected += [ROOT/name for name in ('LICENSE','models.json','image.json','header-policy.json','claude-code-lock.json','CLAUDE_CODE_CHANNEL_CN.md','CLAUDE_CODE_ACCEPTANCE_CN.md','CLAUDE_CODE_SHARED_AUTH_CN.md','CLAUDE_CODE_LIFECYCLE_CN.md','image/migrate_runtime.py') if (ROOT/name).exists()]
    for folder in ('ui','static','security','linux'):
        selected += [p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and 'rendered' not in p.parts]
    selected += [ROOT/'config'/('inspect-'+system) for system in ('darwin','linux')]
    for source in selected:
        dest=stage/source.relative_to(ROOT);dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,dest)
    (stage/'central').mkdir(exist_ok=True)
    for system,name in [('darwin','cli-proxy-api'),('linux','cli-proxy-api-linux-arm64')]:
        source=out/('central-'+system)
        if digest(source)!=build['central'][system]:raise ValueError('central_build_changed')
        shutil.copy2(source,stage/'central'/name)
    image=json.loads((stage/'image.json').read_text());image.update(id=build['image_id'],worker_sha256=build['worker_sha256'],published=False)
    (stage/'image.json').write_text(json.dumps(image,indent=2)+'\n')
    version=(stage/'version.py').read_text().replace("VERSION='container-native7-audit3-export2'","VERSION='container-native7-claude-code-2.1.331'")
    (stage/'version.py').write_text(version)
    files={str(p.relative_to(stage)):digest(p) for p in stage.rglob('*') if p.is_file() and p.name!='release-manifest.json' and '__pycache__' not in p.parts}
    manifest={'candidate':'container-native7-claude-code-2.1.331','published':False,'images':{'id':image['id'],'worker_sha256':image['worker_sha256']},'files':files,'claude_code':build['claude']}
    (stage/'release-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print('Staged isolated package: '+str(stage))
    return stage

if __name__=='__main__':package()

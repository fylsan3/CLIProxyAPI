"""Atomically publish reviewed management assets; never restart or migrate accounts.

Default is a read-only plan. --apply requires the user's UI update authorization.
The live release keeps its own binaries, image IDs, configuration and version.
"""
import argparse, hashlib, http.client, json, os, plistlib, subprocess, tempfile, time
from pathlib import Path

ROOT=Path(__file__).resolve().parent
UI_REVISION='accounts-ui24'
FILES=('build.py','build_page.py','build_inputs.py','ui/app.js','ui/index.html','ui/metrics.js','ui/style.css','ui/quota_view.js','ui/integration.js','ui/linked.js','ui/compiled.js','static/management.local.html')

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def atomic(path,raw,mode=0o644):
    fd,name=tempfile.mkstemp(prefix='.ui-update-',dir=path.parent)
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

def fetch_page():
    c=http.client.HTTPConnection('127.0.0.1',8317,timeout=15)
    try:
        c.request('GET','/accounts.html');r=c.getresponse();raw=r.read()
        if r.status!=200:raise ValueError('management_page_unavailable')
        return raw
    finally:c.close()

def main(apply=False):
    home=Path.home()/'Library/Application Support/CPAContainer'
    plist=Path.home()/'Library/LaunchAgents/com.local.cliproxyapi.plist'
    arguments=plistlib.loads(plist.read_bytes())['ProgramArguments']
    release=Path(next(a for a in arguments if a.endswith('/launch.py'))).parent.resolve()
    if release.parent!=(home/'releases').resolve():raise ValueError('unexpected_live_release')
    manifest_path=release/'release-manifest.json';manifest=json.loads(manifest_path.read_text())
    original={name:(release/name).read_bytes() for name in FILES}
    modes={name:(release/name).stat().st_mode&0o777 for name in FILES}
    for name in FILES:
        if (release/name).is_symlink() or digest(release/name)!=manifest['files'].get(name):raise ValueError('live_file_changed: '+name)
    # A UI-only patch must still use precisely the live pinned native application.
    if digest(ROOT/'static/management.html')!=digest(release/'static/management.html'):raise ValueError('native_asset_changed')
    binary_names=('central/cli-proxy-api','central/cli-proxy-api-linux-arm64','image/worker','image.json','version.py')
    protected={name:digest(release/name) for name in binary_names}
    configuration=digest(home/'state/config.yaml');plist_hash=digest(plist)
    live=fetch_page()
    if hashlib.sha256(live).hexdigest()!=digest(release/'static/management.local.html'):raise ValueError('different_served_release')
    pid_command=['pgrep','-f',str(release/'central/cli-proxy-api')]
    pids=subprocess.check_output(pid_command).decode().split()
    report={'release':str(release),'files':list(FILES),'ui_revision':UI_REVISION,'restart':False,'account_operations':0,'apply':apply}
    if not apply:print(json.dumps(report,indent=2));return
    transaction=home/'transactions'/(UI_REVISION+'-'+str(time.time_ns()));transaction.mkdir(parents=True,mode=0o700)
    for name,raw in original.items():
        destination=transaction/name;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(raw)
    saved_manifest=manifest_path.read_bytes();(transaction/'release-manifest.json').write_bytes(saved_manifest)
    try:
        # Publish the self-contained HTML last; existing tabs keep running old JS.
        for name in FILES:atomic(release/name,(ROOT/name).read_bytes(),modes[name]);manifest['files'][name]=digest(release/name)
        manifest['ui_revision']=UI_REVISION
        atomic(manifest_path,(json.dumps(manifest,indent=2)+'\n').encode())
        if fetch_page()!=(ROOT/'static/management.local.html').read_bytes():raise ValueError('served_ui_mismatch')
        if any(digest(release/n)!=v for n,v in protected.items()):raise ValueError('protected_runtime_changed')
        if digest(home/'state/config.yaml')!=configuration or digest(plist)!=plist_hash:raise ValueError('configuration_changed')
        if subprocess.check_output(pid_command).decode().split()!=pids:raise ValueError('central_process_changed')
    except Exception:
        for name,raw in original.items():atomic(release/name,raw,modes[name])
        atomic(manifest_path,saved_manifest)
        raise
    report.update(transaction=str(transaction),same_central_process=True,runtime_and_configuration_unchanged=True,served_ui_verified=True)
    (transaction/'result.json').write_text(json.dumps(report,indent=2)+'\n')
    (ROOT/'evidence'/f'{UI_REVISION}-publication.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true');main(parser.parse_args().apply)

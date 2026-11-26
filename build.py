"""One build entrypoint for central, worker, inspectors and closed test images."""
import argparse,hashlib,json,os,re,shutil,subprocess,tempfile,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'source'
TOOL=Path(os.environ.get('CPA_BUILD_TOOLS',str(ROOT/'.build-tools'))).resolve()
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def run(cmd,env=None,cwd=None):
 p=subprocess.run(cmd,cwd=cwd,env=env,text=True,capture_output=True)
 if p.returncode:print(p.stdout+p.stderr,flush=True);p.check_returncode()
 return p.stdout.strip()
def check_overrides():
 # Compare the moved declaration map against the immutable manual reference.
 def values(text):
  pairs=re.findall(r'"([a-z-]+)":\s*("[^"\n]*"|platformOS|platformArch)',text)
  return {k:({'platformOS':'Linux','platformArch':'arm64'}.get(v,v.strip('"'))) for k,v in pairs}
 from account_header_policy import load_policy,resolve
 doc,_=load_policy()
 reference=(ROOT/'manual-header-reference.go.txt').read_text().split('values := map[string]string{',1)[1].split('}',1)[0]
 actual=resolve(doc,'model')['set']
 assert actual==values(reference) and len(actual)==12,'manual model override values changed'
 policy=json.loads((ROOT/'header-policy.json').read_text())
 code=(ROOT/'src/internal/util/container_http_headers.go').read_text().split('var containerRequestBlocked = map[string]bool{',1)[1].split('}',1)[0]
 assert set(policy['request_blocked'])==set(re.findall(r'"([^"]+)":\s*true',code)),'header policies diverged'
def build_control():
 """Repackage controller/UI changes without rebuilding or replacing any Go binary/image."""
 from build_inputs import verify_source
 verify_source(ROOT);check_overrides()
 manifest=json.loads((ROOT/'release-manifest.json').read_text())
 def allowed(name):
  p=Path(name)
  return (len(p.parts)==1 and p.suffix=='.py') or (p.parts[0]=='ui' and p.suffix in ('.js','.css','.html')) or name=='static/management.local.html'
 for name,want in manifest['files'].items():
  if not allowed(name) and digest(ROOT/name)!=want:raise ValueError('control_build_cannot_change: '+name)
 image=json.loads((ROOT/'image.json').read_text())
 if any(image[k]!=v for k,v in manifest['images'].items()):raise ValueError('control_build_image_changed')
 run([sys.executable,'-B',str(ROOT/'build_page.py')])
 for p in ROOT.rglob('*'):
  if p.is_file() and allowed(str(p.relative_to(ROOT))):manifest['files'][str(p.relative_to(ROOT))]=digest(p)
 manifest['ui_revision']='accounts-ui16'
 (ROOT/'release-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 print('Controller/UI build complete; Go binaries and container images unchanged.',flush=True)
def build(images=True, runtime_base=None, fixture_base=None):
 for name in ('image','central','config'):(ROOT/name).mkdir(exist_ok=True)
 from build_inputs import verify_source
 verify_source(ROOT)
 from account_header_policy import generate
 generate()
 check_overrides()
 run([sys.executable,'-B',str(ROOT/'build_page.py')])
 mapping=json.loads((ROOT/'overlay-inputs.json').read_text())
 (ROOT/'overlay.json').write_text(json.dumps({'Replace':{str(SOURCE/k):str(ROOT/v) for k,v in mapping.items()}},indent=2))
 overlay=json.loads((ROOT/'overlay.json').read_text())
 for value in overlay['Replace'].values():assert Path(value).is_relative_to(ROOT/'src'),value
 run([str(TOOL/'go/bin/gofmt'),'-w',*[str(p) for p in (ROOT/'src').rglob('*.go')]])
 env=dict(os.environ,GOROOT=str(TOOL/'go'),GOMODCACHE=str(TOOL/'modules'),GOCACHE=str(Path(tempfile.gettempdir())/'cpa-linux-candidate-cache'),GOARCH='arm64',CGO_ENABLED='0',GOTOOLCHAIN='local',GOENV='off',GOPROXY='off',GOSUMDB='off',GOFLAGS='',GOWORK='off')
 def compile(system,out,args,tags=False,overlay_path=None):
  env['GOOS']=system
  cmd=[str(TOOL/'go/bin/go'),'build','-mod=readonly','-p','2','-overlay',str(overlay_path or ROOT/'overlay.json'),'-o',str(out)]
  if args==['./cmd/server']:cmd+=['-ldflags','-X main.Version=8.1.1-container-native7']
  if tags:cmd+=['-tags','cpa_offline']
  run(cmd+args,env,SOURCE);print('Built',out.relative_to(ROOT),flush=True)
 compile('linux',ROOT/'image/worker',[str(SOURCE/'cmd/server/offline_worker_entry.go'),str(SOURCE/'cmd/server/offline_refresh_controller.go'),str(SOURCE/'cmd/server/offline_sample_capture.go'),str(SOURCE/'cmd/server/offline_account_info.go'),str(SOURCE/'cmd/server/offline_http_archive.go'),str(SOURCE/'cmd/server/offline_header_policy.go'),str(SOURCE/'cmd/server/offline_network.go'),str(SOURCE/'cmd/server/offline_capture_session.go')],True)
 compile('linux',ROOT/'central/cli-proxy-api-linux-arm64',['./cmd/server'])
 compile('darwin',ROOT/'central/cli-proxy-api',['./cmd/server'])
 virtual=SOURCE/'cmd/environment-config/main.go'
 cp=ROOT/'config/overlay.json';cp.write_text(json.dumps({'Replace':{str(virtual):str(ROOT/'config/main.go')}}))
 for system in ['darwin','linux']:compile(system,ROOT/'config'/('inspect-'+system),[str(virtual)],overlay_path=cp)
 check_overrides()
 if not images:return
 from host_runtime import docker_cli
 cli=docker_cli()
 base=json.loads((ROOT/'base-images.json').read_text())
 with tempfile.TemporaryDirectory(prefix='cpa-unified-image-') as folder:
  p=Path(folder);shutil.copy2(ROOT/'image/worker',p/'worker');(p/'worker').chmod(0o755)
  runtime_files={'field_provenance.py':'/opt/native/field_provenance.py','account_header_policy.json':'/opt/native/account_header_policy.json','browser_worker.py':'/opt/sample/worker.py','http_archive.py':'/opt/native/http_archive.py','sample_export.py':'/opt/native/sample_export.py','bundle_io.py':'/opt/native/bundle_io.py','entry.py':'/opt/native/entry.py','network_boot.py':'/opt/native/network_boot.py','network_gate.py':'/opt/native/network_gate.py','locale_probe.py':'/opt/native/locale_probe.py','browser_resources.py':'/opt/native/browser_resources.py'}
  instructions='FROM '+(runtime_base or base['id'])+'\nCOPY --chown=1001:1001 worker /opt/native/worker\n'
  for name,destination in runtime_files.items():
   shutil.copy2(ROOT/'image'/name,p/name);instructions+='COPY --chown=1001:1001 '+name+' '+destination+'\n'
  instructions+='RUN rm -f /opt/native/socks_adapter.py\n'
  (p/'Dockerfile').write_text(instructions)
  image=run(cli+['build','--network','none','-q',str(p)])
 from prepare_test_certificates import prepare
 prepare()
 tls=run(cli+['build','--network','none','--build-arg','BASE='+image,'-q',str(ROOT/'tls-test')])
 fixture=run(cli+['build','--network','none','--build-arg','BASE='+(fixture_base or base['tls_fixture']),'-q',str(ROOT/'tls-fixture')])
 base.update(id=image,tls_test=tls,tls_fixture=fixture,worker_sha256=digest(ROOT/'image/worker'),published=False)
 (ROOT/'image.json').write_text(json.dumps(base,indent=2)+'\n')
 files={}
 for p in ROOT.rglob('*'):
  if not p.is_file() or any(x in p.relative_to(ROOT).parts for x in ['evidence','tests','__pycache__','.git','.build-tools']):continue
  if p.name=='release-manifest.json':continue
  files[str(p.relative_to(ROOT))]=digest(p)
 (ROOT/'release-manifest.json').write_text(json.dumps({'candidate':'container-native7','build_runtime_base':runtime_base or base['id'],'published':False,'images':{k:base[k] for k in ['id','tls_test','tls_fixture']},'manual_overrides_unchanged':False,'container_derived_headers':['X-Stainless-OS','X-Stainless-Arch'],'other_manual_overrides_unchanged':True,'files':files},indent=2)+'\n')
 print('Unified build complete; production not modified.',flush=True)
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--runtime-base',help='Explicit local build base override; never rewrites frozen base-images.json');parser.add_argument('--fixture-base',help='Existing local fixture build base');modes=parser.add_mutually_exclusive_group();modes.add_argument('--compile-only',action='store_true');modes.add_argument('--control-only',action='store_true');args=parser.parse_args()
 if args.control_only:build_control()
 else:build(not args.compile_only,args.runtime_base,args.fixture_base)

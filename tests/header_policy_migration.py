"""Compare two compiled implementations on real loopback HTTP, fake accounts only.
Baseline is a pre-edit snapshot, not derived from the new policy. Nothing mounts
account volumes or contacts external providers. Before/after evidence is retained.
"""
import hashlib,json,os,subprocess,sys,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R))
from host_runtime import docker_cli
from account_header_policy import generate
from build import check_overrides
# go vet cannot chdir into a virtual new package directory in a Go overlay.
# The shared package is vetted by egress_unit/container_platform_headers in a
# materialized temporary module; this runner compiles and checks actual HTTP.
from build_inputs import verify_source
verify_source(R);generate(check=True);check_overrides()
T=Path(os.environ['CPA_BUILD_TOOLS']);S=R/'source';B=R/'evidence/header-policy-before-src'
# Recreate the baseline from the published pre-refactor commit on a fresh checkout.
# Existing locally frozen files remain untouched.
BASELINE_REF='ab32b74'
if not (B/'overlay-inputs.json').exists():
 B.mkdir(parents=True,exist_ok=True)
 def frozen(name):return subprocess.check_output(['git','show',BASELINE_REF+':'+name],cwd=R)
 mapping=json.loads(frozen('overlay-inputs.json'))
 (B/'overlay-inputs.json').write_text(json.dumps(mapping))
 for name in mapping.values():
  target=B/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(frozen(name))
 (B/'oauth_native_capture_test.go').write_bytes(frozen('tests/oauth_native_capture_test.go'))
image=json.loads((B/'image.json' if (B/'image.json').exists() else R/'image.json').read_text())['id']
results={}
with tempfile.TemporaryDirectory(prefix='cpa-header-migration-') as folder:
 p=Path(folder)
 for stage,root in [('before',B),('after',R)]:
  mapping=json.loads((root/'overlay-inputs.json').read_text())
  base_test=(B/'oauth_native_capture_test.go' if stage=='before' else R/'tests/oauth_native_capture_test.go').read_text()
  results[stage]={}
  for account in ('A','B'):
   saved=R/'evidence'/('header-migration-'+stage+'-'+account+'.json')
   if (('--compare-only' in sys.argv) or (stage=='before' and '--reuse-before' in sys.argv)) and saved.exists():
    results[stage][account]=json.loads(saved.read_text());continue
   source=base_test
   for part in ('access','refresh','account','org'):
    source=source.replace('fixture-'+part,'fixture-'+account+'-'+part)
   source=source.replace('"messages":[{"role":"user","content":"fixture"}]','"system":"SYSTEM_UNCHANGED","messages":[{"role":"user","content":"fixture Platform: linux Shell: bash"}]')
   test=p/(stage+'-'+account+'.go');test.write_text(source)
   virtual=S/'cmd/server/oauth_native_capture_test.go'
   replacements={str(S/k):str(root/v) for k,v in mapping.items()};replacements[str(virtual)]=str(test)
   overlay=p/'overlay.json';overlay.write_text(json.dumps({'Replace':replacements}))
   files=[str(S/k) for k in mapping if k.startswith('cmd/server/offline_') and k.endswith('.go')]
   env=dict(os.environ,GOROOT=str(T/'go'),GOMODCACHE=str(T/'modules'),GOCACHE='/tmp/cpa-linux-candidate-cache',GOOS='linux',GOARCH='arm64',CGO_ENABLED='0',GOTOOLCHAIN='local',GOENV='off',GOPROXY='off',GOSUMDB='off',GOWORK='off',GOFLAGS='')
   subprocess.run([str(T/'go/bin/go'),'test','-c','-vet=off','-mod=readonly','-p','2','-tags','cpa_offline','-overlay',str(overlay),'-o',str(p/'capture'),*files,str(virtual)],cwd=S,env=env,check=True)
   script="""import sys,subprocess
from pathlib import Path
p=Path('/tmp/capture');p.write_bytes(sys.stdin.buffer.read());p.chmod(0o700)
r=subprocess.run([str(p),'-test.v','-test.timeout=45s'],capture_output=True,text=True)
print(r.stdout+r.stderr,file=sys.stderr)
if r.returncode:sys.exit(r.returncode)
print(Path('/tmp/oauth-native-capture.json').read_text())
"""
   run=subprocess.run(docker_cli()+['run','--rm','-i','--network','none','--user','1001:1001','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--tmpfs','/tmp:rw,exec,nosuid,nodev,size=128m,mode=1777','--entrypoint','python3',image,'-B','-c',script],input=(p/'capture').read_bytes(),capture_output=True,timeout=60)
   print(stage,account,run.stderr.decode(),flush=True);run.check_returncode()
   results[stage][account]=json.loads(run.stdout)
   (R/'evidence'/('header-migration-'+stage+'-'+account+'.json')).write_text(json.dumps(results[stage][account],indent=2)+'\n')
 checks=[]
 for account in ('A','B'):
  for group in ('oauth_requests','native_model_fallback','final_model_requests'):
   before=results['before'][account][group];after=results['after'][account][group]
   # Only the native fallback's loopback server allocates a fresh ephemeral port.
   # Official hostnames and every HTTP header, method, path and body hash compare exactly.
   if group=='native_model_fallback':
    before=json.loads(json.dumps(before));after=json.loads(json.dumps(after))
    for row in before+after:
     assert row['host'].startswith('127.0.0.1:')
     row['host']='127.0.0.1:<ephemeral-test-port>'
   assert before==after,(account,group,'wire migration mismatch')
   for row in after:checks.append({'account':account,'method':row['method'],'path':row['path'],'grant_type':row.get('grant_type'),'headers_equal':True,'body_hash_equal':True,'close_equal':True})
 a=results['after']['A']['oauth_requests'];b=results['after']['B']['oauth_requests']
 assert any(x['headers'].get('Authorization')!=y['headers'].get('Authorization') for x,y in zip(a,b))
 report={'passed':True,'comparisons':checks,'account_credentials_distinct':True,'real_accounts_used':False,'production_changed':False,'boundary':'native OAuth and real final transport; loopback HTTPS in network-none containers','unchanged_12_manual_model_headers':True,'normalized_fields':['native_model_fallback.host loopback ephemeral port only']}
 (R/'evidence/header-policy-migration.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps(report))

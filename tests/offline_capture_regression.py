"""Run export regressions in an existing image, network disabled, no account mounts."""
import io,json,subprocess,sys,tarfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from host_runtime import docker_cli

def main():
    image=json.loads((ROOT/'image.json').read_text())['id']
    data=io.BytesIO()
    with tarfile.open(fileobj=data,mode='w') as archive:
        for folder,pattern in [(ROOT,'*.py'),(ROOT/'image','*.py'),(ROOT/'tests','*_test.py')]:
            for file in folder.glob(pattern):archive.add(file,arcname=str(file.relative_to(ROOT)))
        archive.add(ROOT/'image/account_header_policy.json',arcname='image/account_header_policy.json')
    bootstrap="""import io,tarfile,sys,unittest
from pathlib import Path
root=Path('/tmp/work');root.mkdir()
with tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read())) as archive:archive.extractall(root,filter='data')
sys.path[:0]=[str(root),str(root/'image'),str(root/'tests')]
suite=unittest.TestSuite();loader=unittest.TestLoader()
for pattern in ['capture_export_fixes_test.py','sample_export_test.py','refresh_capture_status_test.py','field_provenance_test.py']:
    suite.addTests(loader.discover(str(root/'tests'),pattern=pattern))
result=unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(not result.wasSuccessful())
"""
    command=docker_cli()+['run','--rm','--pull=never','--network','none','--read-only','--cap-drop','ALL','--user','1001:1001','--memory','512m','--cpus','2','--tmpfs','/tmp:rw,nosuid,nodev,size=64m,mode=1777','-i','--entrypoint','python3',image,'-B','-c',bootstrap]
    result=subprocess.run(command,input=data.getvalue(),capture_output=True,timeout=90)
    output=(result.stdout+result.stderr).decode()
    (ROOT/'evidence').mkdir(exist_ok=True)
    (ROOT/'evidence/export-fixes-tests.log').write_text(output)
    print(output);return result.returncode

if __name__=='__main__':raise SystemExit(main())

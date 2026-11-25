"""Verify prerequisites before either Linux role starts."""
import json,os,platform,socket,sys
from pathlib import Path
role,app=sys.argv[1:];app=Path(app);sys.path.insert(0,str(app))
from version import release_info
release_info()
if sys.platform!='linux' or platform.machine()!='aarch64':raise SystemExit('linux_arm64_required_for_this_package')
if role=='central':
    if os.geteuid()==0:raise SystemExit('dedicated_central_user_required')
    from network_guard import enforce
    enforce()
    with socket.socket(socket.AF_UNIX) as s:s.connect('/run/cpa-control/model.sock')
    if os.access('/var/run/docker.sock',os.W_OK):raise SystemExit('central_must_not_access_docker')
elif role=='broker':
    from host_runtime import docker_cli
    import subprocess
    info=json.loads(subprocess.check_output(docker_cli()+['image','inspect',release_info()['image']],text=True))[0]
    if info.get('Architecture')!='arm64':raise SystemExit('account_image_architecture_mismatch')
    network=json.loads(Path('/var/lib/cpa-broker/private/network-fixture.json').read_text())
    if network.get('mode') not in ('managed','closed_tls_test','closed_test'):raise SystemExit('network_config_required')
else:raise SystemExit('unknown_role')

"""Select one explicitly local Docker engine for every control-plane component."""
import os,shutil,sys
from pathlib import Path

def docker_cli():
    binary=os.environ.get('CPA_DOCKER_BINARY') or shutil.which('docker')
    if not binary:
        binary='/opt/homebrew/bin/docker' if sys.platform=='darwin' else '/usr/bin/docker'
    endpoint=os.environ.get('CPA_DOCKER_HOST') or os.environ.get('DOCKER_HOST')
    if not endpoint:
        endpoint='unix://'+str(Path.home()/'.colima/cpa-local/docker.sock') if sys.platform=='darwin' else 'unix:///var/run/docker.sock'
    if not endpoint.startswith('unix:///') or '\n' in endpoint:
        raise ValueError('local_unix_docker_endpoint_required')
    return [binary,'--host',endpoint]

def docker_socket():return Path(docker_cli()[2][7:])

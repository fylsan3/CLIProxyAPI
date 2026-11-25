"""Read the non-persistent network gate before opening any account state."""
import json
import os
from pathlib import Path
import socket
import stat
import time


def check():
    if os.environ.get('NETWORK_STAGE') == 'maintenance':
        if {name for _, name in socket.if_nameindex()} != {'lo'}:
            raise ValueError('maintenance_network_not_isolated')
        return
    proof = Path('/run/network/firewall.json')
    info = proof.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError('network_firewall_unverified')
    fixed = json.loads(proof.read_text())
    if fixed.get('config_sha256') != os.environ.get('PROXY_CONFIG_SHA256'):
        raise ValueError('network_binding_mismatch')
    if fixed.get('egress_manager')!='go' or fixed.get('egress_uid')!=1002:
        raise ValueError('go_egress_unverified')
    live=Path('/run/network/live/status.json');info=live.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=1002 or info.st_mode & 0o022:
        raise ValueError('network_status_untrusted')
    status = json.loads(live.read_text())
    age = time.time() - status.get('checked_at', 0)
    if status.get('owner') != os.environ['FIXTURE_OWNER'] or not status.get('healthy') or not 0 <= age < 2:
        raise ValueError('account_proxy_unavailable')

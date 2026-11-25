"""Install a single SOCKS peer policy before dropping all account-process capabilities."""
import hashlib
import ipaddress
from account_identity import valid_owner
import json
import os
from pathlib import Path
import subprocess


def run():
    path = Path('/network-config/config.json')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != os.environ['PROXY_CONFIG_SHA256']:
        raise ValueError('network_binding_mismatch')
    config = json.loads(raw)
    if config.get('provider') not in ('mock-claude','claude-subscription') or config.get('provider')!=os.environ.get('CPA_PROVIDER') or (config.get('provider')=='mock-claude' and config.get('test_only') is not True) or not valid_owner(config['owner']) or config['owner'] != os.environ['FIXTURE_OWNER']:
        raise ValueError('closed_test_required')
    from zoneinfo import ZoneInfo
    ZoneInfo(config['timezone'])
    if (os.environ.get('TZ') != config['timezone'] or config.get('language') != 'en-US' or
        os.environ.get('LANG') != 'C.UTF-8' or os.environ.get('LC_ALL') != 'C.UTF-8' or os.environ.get('LANGUAGE') != 'en_US:en'):
        raise ValueError('locale_binding_mismatch')
    if Path('/etc/timezone').read_text().strip() != config['timezone'] or Path('/etc/localtime').read_bytes() != (Path('/usr/share/zoneinfo') / config['timezone']).read_bytes():
        raise ValueError('system_timezone_mismatch')
    address = ipaddress.ip_address(config['proxy_ip'])
    port = config['proxy_port']
    if not isinstance(port, int) or not 0 < port < 65536:
        raise ValueError('proxy_port_invalid')
    versions = {}
    for version, binary in ((4, 'iptables-nft'), (6, 'ip6tables-nft')):
        def rule(*args):
            subprocess.run([binary, '-w', '3', *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        rule('-P', 'OUTPUT', 'DROP')
        rule('-F', 'OUTPUT')
        if address.version == version:
            rule('-A', 'OUTPUT', '-p', 'tcp', '-d', str(address), '--dport', str(port), '-j', 'ACCEPT')
        # These precede loopback access, also preventing Docker's embedded DNS.
        rule('-A', 'OUTPUT', '-p', 'udp', '--dport', '53', '-j', 'DROP')
        rule('-A', 'OUTPUT', '-p', 'tcp', '--dport', '53', '-j', 'DROP')
        rule('-A', 'OUTPUT', '-o', 'lo', '-d', '127.0.0.1' if version == 4 else '::1', '-p', 'tcp', '-j', 'ACCEPT')
        rule('-A', 'OUTPUT', '-j', 'DROP')
        rules = subprocess.check_output([binary, '-S', 'OUTPUT'])
        versions[str(version)] = hashlib.sha256(rules).hexdigest()
    root = Path('/run/network')
    root.mkdir(mode=0o755)
    proof = root / 'firewall.json'
    proof.write_text(json.dumps({'config_sha256': os.environ['PROXY_CONFIG_SHA256'], 'rules': versions}))
    proof.chmod(0o644)
    for name in ('status.json', 'lifecycle.json'):
        file = root / name
        file.write_text('{}')
        file.chmod(0o600)
        os.chown(file, 1001, 1001)
    # The monitor updates status in a private child directory via atomic rename.
    state = root / 'live'
    state.mkdir(mode=0o700)
    os.chown(state, 1001, 1001)
    os.environ['HOME']='/state/desktop-home'
    os.execvp('setpriv', ['setpriv', '--reuid=1001', '--regid=1001', '--clear-groups',
                         '--bounding-set=-all', '--inh-caps=-all', '--ambient-caps=-all', '--no-new-privs',
                         'python3', '-B', '/opt/native/entry.py'])


if __name__ == '__main__':
    try:
        run()
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        raise SystemExit('account_network_boot_failed')

"""Isolated retention controller. Uses fake A/B, pinned images and network=none only."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parent
from retention import atomic, private, read_json, write_json
from lifecycle import Lease

from host_runtime import docker_cli
DOCKER = docker_cli()


def docker(*args, timeout=60):
    return subprocess.check_output([*DOCKER, *args], text=True, stderr=subprocess.PIPE, timeout=timeout).strip()


class Control:
    def __init__(self, folder):
        os.umask(0o077)
        self.folder = Path(folder)
        self.folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        private(self.folder, directory=True)
        self.lease = Lease(self.folder / '.control.lock')
        self.image = json.loads((ROOT / 'image.json').read_text())['id']

    def close(self):
        self.lease.close()

    def card(self, owner):
        if owner not in ('A', 'B'):
            raise ValueError('fictional_owner_required')
        return self.folder / (owner + '.json')

    def load(self, owner):
        card = read_json(self.card(owner))
        if card['owner'] != owner or card['image'] != self.image:
            raise ValueError('card_image_mismatch')
        for key in ('volume', 'backup'):
            info = json.loads(docker('volume', 'inspect', card[key]))[0]
            if (info['Driver'] != 'local' or info.get('Options') or
                info.get('Labels', {}).get('cpa.retention.id') != card['environment_id']):
                raise ValueError('volume_binding_mismatch')
        return card

    def args(self, card, state_volume=None):
        return ['--pull=never', '--network', 'none', '--read-only', '--init', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--memory', '1g', '--pids-limit', '300',
                '--shm-size', '96m', '--tmpfs', '/tmp:rw,nosuid,nodev,size=192m,mode=1777',
                '--label', 'cpa.retention.id=' + card['environment_id'],
                '--mount', 'type=volume,source=' + (state_volume or card['volume']) + ',target=/state',
                '--mount', 'type=volume,source=' + card['backup'] + ',target=/backup',
                '-e', 'FIXTURE_OWNER=' + card['owner'], '-e', 'ENVIRONMENT_ID=' + card['environment_id'],
                '-e', 'EXPECTED_RUNTIME=' + json.dumps(card['runtime'], sort_keys=True),
                '-e', 'OFFLINE_CENTRAL_REFRESH=1']

    def helper(self, card, action, *args, state_volume=None):
        return docker('run', '--rm', *self.args(card, state_volume), '--entrypoint', 'python3',
                      card['image'], '-B', '/opt/native/retention_cli.py', action, *args)

    def create(self, owner):
        path = self.card(owner)
        if path.exists():
            raise ValueError('account_card_exists_no_reinitialize')
        ident = str(uuid.uuid4())
        name = 'retention-' + ident
        inventory = json.loads(docker('run', '--rm', '--network', 'none', '--entrypoint', 'python3',
                                     self.image, '-B', '/opt/native/retention_cli.py', 'inventory'))
        card = {'owner': owner, 'environment_id': ident, 'image': self.image, 'runtime': inventory,
                'volume': name + '-state', 'backup': name + '-backup', 'status': 'creating'}
        write_json(path, card)
        for volume in (card['volume'], card['backup']):
            docker('volume', 'create', '--label', 'cpa.retention.id=' + ident, volume)
        self.helper(card, 'initialize')
        card['container'] = docker('create', '--name', name, *self.args(card), self.image)
        card['status'] = 'ready_for_offline_test'
        write_json(path, card)
        self.start(owner)
        return card

    def inspect(self, card):
        info = json.loads(docker('inspect', card['container']))[0]
        mounts = {m['Destination']: m for m in info['Mounts'] if m['Destination'] != '/tmp'}
        if (info['Image'] != card['image'] or info['HostConfig']['NetworkMode'] != 'none' or
            set(mounts) != {'/state', '/backup'} or
            any(mounts[target].get('Name') != card[key] for target, key in [('/state', 'volume'), ('/backup', 'backup')])):
            raise ValueError('container_binding_mismatch')
        return info

    def start(self, owner):
        card = self.load(owner)
        self.inspect(card)
        return docker('start', card['container'])

    def snapshot(self, owner, name):
        card = self.load(owner)
        self.inspect(card)
        docker('stop', '-t', '15', card['container'])
        result = self.helper(card, 'snapshot', name)
        docker('start', card['container'])
        return result

    def restore_new_volume(self, owner, snapshot):
        card = self.load(owner)
        info = self.inspect(card)
        if info['State']['Running']:
            raise ValueError('stop_account_before_restore')
        # The previous volume and container remain intact for investigation.
        fresh = 'retention-' + card['environment_id'] + '-restore-' + uuid.uuid4().hex[:8]
        docker('volume', 'create', '--label', 'cpa.retention.id=' + card['environment_id'], fresh)
        self.helper(card, 'restore', snapshot, state_volume=fresh)
        new = dict(card, volume=fresh)
        new['container'] = docker('create', *self.args(new), self.image)
        new['previous'] = {'container': card['container'], 'volume': card['volume']}
        write_json(self.card(owner), new)
        self.start(owner)
        return new


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--state', type=Path, required=True)
    p.add_argument('action', choices=['create', 'start', 'snapshot', 'restore'])
    p.add_argument('owner', choices=['A', 'B'])
    p.add_argument('snapshot', nargs='?')
    args = p.parse_args()
    control = Control(args.state)
    if args.action == 'create':
        result = control.create(args.owner)
    elif args.action == 'start':
        result = control.start(args.owner)
    elif args.action == 'snapshot':
        result = control.snapshot(args.owner, args.snapshot)
    else:
        result = control.restore_new_volume(args.owner, args.snapshot)
    print(json.dumps(result))

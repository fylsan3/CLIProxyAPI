"""Render Linux deployment artifacts; never install or start host services."""
import argparse,json,os,re,shutil
from pathlib import Path

def render(app,out,network,port=8318):
    for value in (str(app),str(network)):
        if not re.fullmatch(r'/[A-Za-z0-9_./-]+',value) or '..' in Path(value).parts:raise ValueError('absolute_simple_install_paths_required')
    if not 1024<=port<=65535:raise ValueError('invalid_port')
    out.mkdir(mode=0o700,parents=True,exist_ok=False)
    common='''Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6
CapabilityBoundingSet=
TimeoutStopSec=3700
'''
    broker=f'''[Unit]
StartLimitIntervalSec=0
Description=CPA account container controller
Wants=docker.service
After=docker.service local-fs.target
RequiresMountsFor=/var/lib/cpa-broker
[Service]
Type=simple
User=cpa-broker
Group=cpa-broker
SupplementaryGroups=cpa-control docker
RuntimeDirectory=cpa-control
RuntimeDirectoryMode=0750
Environment=CPA_DOCKER_BINARY=/usr/bin/docker
Environment=CPA_DOCKER_HOST=unix:///var/run/docker.sock
ExecStartPre=/usr/bin/python3 -B {app}/linux/preflight.py broker {app}
ExecStart=/usr/bin/python3 -B {app}/broker.py /var/lib/cpa-broker/private /run/cpa-control/model.sock --control-group cpa-control
WorkingDirectory=/var/lib/cpa-broker
ReadWritePaths=/var/lib/cpa-broker /run/cpa-control
{common}[Install]
WantedBy=multi-user.target
'''
    # systemd creates RuntimeDirectory with the primary group; use a separate
    # shared control group for the broker so the socket directory is accessible.
    broker=broker.replace('Group=cpa-broker\nSupplementaryGroups=cpa-control docker','Group=cpa-control\nSupplementaryGroups=cpa-broker docker')
    central=f'''[Unit]
StartLimitIntervalSec=0
Description=CPA central dispatcher
Wants=cpa-account-broker.service
After=cpa-account-broker.service local-fs.target
RequiresMountsFor=/var/lib/cpa-central
[Service]
Type=simple
User=cpa-central
Group=cpa-central
SupplementaryGroups=cpa-control
Environment=HOME=/var/lib/cpa-central
Environment=CPA_CONTAINER_ROUTING=1
Environment=CPA_CONTAINER_SOCKET=/run/cpa-control/model.sock
Environment=MANAGEMENT_STATIC_PATH={app}/static
ExecStartPre=/usr/bin/python3 -B {app}/linux/preflight.py central {app}
ExecStart=/usr/bin/python3 -B {app}/linux/network_guard.py -- {app}/central/cli-proxy-api-linux-arm64 -config /var/lib/cpa-central/config.yaml -local-model
WorkingDirectory=/var/lib/cpa-central
ReadWritePaths=/var/lib/cpa-central
InaccessiblePaths=-/var/lib/cpa-broker -/run/docker.sock -/var/run/docker.sock
{common}[Install]
WantedBy=multi-user.target
'''
    (out/'cpa-account-broker.service').write_text(broker)
    (out/'cpa-central.service').write_text(central)
    (out/'sysusers.conf').write_text('g cpa-control -\nu cpa-broker - "CPA account controller" /var/lib/cpa-broker\nu cpa-central - "CPA central dispatcher" /var/lib/cpa-central\n')
    (out/'deployment.json').write_text(json.dumps({'app':str(app),'network_config':str(network),'port':port,'architecture':'arm64','target_host_verified':False,'installed':False},indent=2))
    shutil.copy2(Path(__file__).with_name('install.py'),out/'install.py')
    print('Rendered deployment package; nothing installed or enabled.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--app',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--network-config',type=Path,required=True);p.add_argument('--port',type=int,default=8318)
    a=p.parse_args();render(a.app,a.output,a.network_config,a.port)

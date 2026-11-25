"""Explicit root installation for a new target only. Does not enable/start units."""
import json,os,pwd,grp,secrets,shutil,subprocess,sys
from pathlib import Path

def run():
    if sys.platform!='linux' or os.geteuid()!=0:raise SystemExit('run on target Linux as root')
    root=Path(__file__).resolve().parent;spec=json.loads((root/'deployment.json').read_text());app=Path(spec['app'])
    central=Path('/var/lib/cpa-central');broker=Path('/var/lib/cpa-broker')
    if central.exists() or broker.exists():raise SystemExit('existing_state_not_overwritten; migration required')
    for unit in ('cpa-central.service','cpa-account-broker.service'):
        if (Path('/etc/systemd/system')/unit).exists():raise SystemExit('existing_service_not_overwritten')
    sys.path.insert(0,str(app));from version import release_info
    release_info()
    network=json.loads(Path(spec['network_config']).read_text())
    if network.get('mode') not in ('managed','closed_test','closed_tls_test'):raise SystemExit('invalid_network_configuration')
    subprocess.run(['systemd-sysusers',str(root/'sysusers.conf')],check=True)
    key=secrets.token_hex(24);os.umask(0o077)
    for path in (central,central/'auth-empty',broker,broker/'private',broker/'backups'):path.mkdir(mode=0o700)
    cfg={'host':'127.0.0.1','port':spec['port'],'auth-dir':str(central/'auth-empty'),'api-keys':[key],
         'remote-management':{'secret-key':key,'disable-control-panel':False},'request-log':False,
         'routing':{'strategy':'fill-first','retry':{'request-retry':0,'max-retry-interval':0}}}
    (central/'config.yaml').write_text(json.dumps(cfg));(central/'client-key').write_text(key)
    (broker/'private/network-fixture.json').write_text(json.dumps(network))
    (broker/'private/central-view.json').write_text(json.dumps({'port':spec['port'],'key':key}))
    from portable_backup import configure_destination
    configure_destination(broker/'private',broker/'backups')
    # The private key copy exists solely for the controller's authenticated status calls.
    for base,user in ((central,'cpa-central'),(broker,'cpa-broker')):
        person=pwd.getpwnam(user)
        for path in [base,*base.rglob('*')]:os.chown(path,person.pw_uid,person.pw_gid)
    for unit in ('cpa-central.service','cpa-account-broker.service'):shutil.copy2(root/unit,Path('/etc/systemd/system')/unit)
    subprocess.run(['systemctl','daemon-reload'],check=True)
    print('Installed, not started. Enable/start cpa-central.service after preflight. No accounts imported.')
if __name__=='__main__':run()

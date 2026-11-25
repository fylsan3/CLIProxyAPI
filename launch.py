"""Start the Mac offline candidate as one managed process tree, without production access."""
import argparse,contextlib,hashlib,json,os,secrets,signal,socket,sqlite3,subprocess,sys,time,urllib.request
from pathlib import Path
from lab_support import ROOT,docker,wait,stop,mac_profile
from lifecycle import Lease
from storage_guard import private_directory,private_file
from version import release_info


def run():
    parser=argparse.ArgumentParser();parser.add_argument('--state',type=Path,default=ROOT/'run')
    parser.add_argument('--max-request-body-bytes',type=int);parser.add_argument('--port',type=int,default=0);parser.add_argument('--dashboard-port',type=int,default=0)
    parser.add_argument('--backup-directory',type=Path);network_args=parser.add_mutually_exclusive_group(required=True);network_args.add_argument('--network-fixture',type=Path);network_args.add_argument('--network-config',type=Path);parser.add_argument('--refresh-workers',type=int);parser.add_argument('--ephemeral',action='store_true');parser.add_argument('--check',action='store_true');args=parser.parse_args()
    info=release_info()
    if args.check:
        print(json.dumps(dict(info,host_start_supported=sys.platform in ('darwin','linux'),launch_method='systemd split services' if sys.platform=='linux' else 'supervised process tree',linux_target_verified=False),indent=2));return
    if sys.platform=='linux':
        raise SystemExit('Linux uses the split systemd services. Run linux/deploy.py with --app, --output and --network-config, then install the generated package; see linux/README_CN.md.')
    if sys.platform!='darwin':raise SystemExit('unsupported_host')
    from preflight import check
    readiness=check(args.state,args.backup_directory)
    if not readiness['ready']:raise ValueError('startup_capacity_check_failed: '+','.join(readiness['issues']))
    from control_backup import startup_lease
    os.umask(0o077);state=args.state.resolve();lease=startup_lease(state)
    stopping=False
    def requested(*unused):
        nonlocal stopping
        stopping=True
    signal.signal(signal.SIGTERM,requested);signal.signal(signal.SIGINT,requested)
    private=state/'broker-private';sock=state/'.test-projects.sock';scope=None;children=[]
    try:
        docker('image','inspect',info['image'])
        private_directory(state/'auth-empty')
        from saved_config import prepare
        cfgpath,keypath,key,port=prepare(ROOT,state,args.port,args.refresh_workers,args.max_request_body_bytes)
        private_directory(private)
        if args.backup_directory:
            from portable_backup import configure_destination
            configure_destination(private,args.backup_directory)
        fixture_path=private/'network-fixture.json';private_file(fixture_path)
        fixture_raw=(args.network_fixture or args.network_config).read_text()
        selected=json.loads(fixture_raw)
        if args.network_config and selected.get('mode')!='managed':raise ValueError('managed_network_config_required')
        if args.network_fixture and selected.get('mode','closed_test') not in ('closed_test','closed_tls_test'):raise ValueError('test_network_required')
        if fixture_path.exists() and json.loads(fixture_path.read_text())!=json.loads(fixture_raw):raise ValueError('saved_network_fixture_changed_no_overwrite')
        if not fixture_path.exists():fixture_path.write_text(fixture_raw)
        view=private/'central-view.json';private_file(view);view.write_text(json.dumps({'port':port,'key':key}))
        with contextlib.ExitStack() as files:
            log=files.enter_context((state/'broker.log').open('ab'))
            broker=subprocess.Popen([sys.executable,'-B',str(ROOT/'broker.py'),str(private),str(sock)],stdout=log,stderr=log)
            children.append(broker)
            wait(lambda:sock.is_socket())
            with sqlite3.connect(private/'control.sqlite') as db:scope=db.execute('SELECT scope FROM meta').fetchone()[0]
            central_log=files.enter_context((state/'central.log').open('ab'))
            central=subprocess.Popen(['/usr/bin/sandbox-exec','-p',mac_profile([sock],[private,Path.home()/'cliproxyapi'],__import__('host_runtime').docker_socket()),str(ROOT/'central/cli-proxy-api'),'-config',str(cfgpath),'-local-model'],cwd=state,env={'HOME':str(state),'TMPDIR':str(state),'PATH':'/usr/bin:/bin','CPA_CONTAINER_ROUTING':'1','MANAGEMENT_STATIC_PATH':str(ROOT/'static')},stdout=central_log,stderr=central_log)
            children.append(central)
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def healthy():
                try:
                    with opener.open('http://127.0.0.1:'+str(port)+'/healthz',timeout=.5) as r:return r.status==200
                except OSError:return False
            wait(healthy)
            from central_view import central_request
            wait(lambda:central_request(view,'pool',{})[0]==200)
            panel={'url':'http://127.0.0.1:'+str(port)+'/accounts.html'}
            (state/'launch.json').write_text(json.dumps({'release':info,'api_base':'http://127.0.0.1:'+str(port)+'/v1','api_key_file':str(keypath),'model':'test-project-shared' if selected.get('mode','closed_test')=='closed_test' else 'claude-sonnet-4-5','management_url':panel['url'],'ephemeral':args.ephemeral},indent=2))
            print('candidate_ready; connection details: '+str(state/'launch.json'),flush=True)
            while not stopping:
                if any(p.poll() is not None for p in children):raise RuntimeError('candidate_child_exited')
                time.sleep(.2)
    finally:
        for process in reversed(children):stop(process)
        if args.ephemeral and scope:
            for listing,remove in [(['ps','-a'],['rm','-f']),(['volume','ls'],['volume','rm'])]:
                ids=docker(*listing,'--filter','label=cpa.native.scope='+scope,'-q').split()
                if ids:docker(*remove,*ids)
            for card_path in (private/'environments').glob('*.json'):
                card=json.loads(card_path.read_text())
                if 'environment_id' not in card or 'container' not in card:continue
                ident=card['environment_id']
                for listing,remove in [(['ps','-a'],['rm','-f']),(['volume','ls'],['volume','rm'])]:
                    ids=docker(*listing,'--filter','label=cpa.retention.id='+ident,'-q').split()
                    if ids:docker(*remove,*ids)
            # A disposable run must not leave stale account bindings for the next start.
            if (private/'control.sqlite').exists():
                with sqlite3.connect(private/'control.sqlite') as db:db.execute('DELETE FROM bindings')
        (state/'launch.json').unlink(missing_ok=True);lease.close()
    print('candidate_stopped',flush=True)

if __name__=='__main__':run()

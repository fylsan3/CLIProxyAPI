"""Fixed local consent and file task in one network-disabled Ubuntu container."""
import hashlib, http.server, json, os, secrets, signal, socket, socketserver, subprocess, sys, threading, time
from pathlib import Path
from urllib.parse import urlsplit
from desktop import Desktop
from account_identity import valid_owner
from sandbox_status import wait_for_sandbox
def restore_browser(pid):
    # Keep X11 window-close races out of the persistent browser controller.
    try:
        subprocess.run([sys.executable,'-B','/opt/sample/window_control.py',str(pid)],
                       check=True,timeout=4,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    except (OSError,subprocess.SubprocessError):raise ValueError('browser_restore_unavailable')
import base64, atexit
from chrome_shutdown import close_windows
sys.path.insert(0,"/opt/native")
from profile_store import ProfileStore, ProfileError, atomic_json, regular
from browser_resources import MemoryObserver, memory_snapshot

owner=os.environ["FIXTURE_OWNER"]
assert valid_owner(owner)
os.umask(0o077)
state=Path("/state")
local="/tmp/fixture-control.sock"
def save(name,data):
    atomic_json(state/name,data)
def chrome_pids():
    found=[]
    for p in Path("/proc").glob("[0-9]*/cmdline"):
        try:
            # Chromium rewrites child argv into a space-separated process title.
            args=p.read_bytes().replace(b'\0',b' ').split()
            if args and Path(os.fsdecode(args[0])).name in ("chrome","chrome_crashpad_handler","headless_shell","chrome-headless-shell"):found.append(int(p.parent.name))
        except OSError:pass
    return found
def command(data):
    with socket.socket(socket.AF_UNIX) as s:
        s.settimeout(16);s.connect(local);s.sendall(json.dumps(data).encode()+b"\n")
        return json.loads(s.makefile("rb").readline(524288))
if sys.argv[1]=="request":
    print(json.dumps(command(json.load(sys.stdin))));sys.exit()

class Worker:
    def __init__(self):
        self.desktop=Desktop();self.lock=threading.Lock();self.browser=None;self.seen=threading.Event();self.consent=threading.Event();self.ack=threading.Event();self.path=""
        self.last_close=None;self.target=None;self.sandbox=None;self.diagnostics=[];self.diagnostic_reader=None
        self.memory_observer=MemoryObserver(lambda event:save('browser-memory-diagnostics.json',event))
        self.store=None;self.failure=None
        try:self.store=ProfileStore(state,owner)
        except (ProfileError,OSError,ValueError) as error:
            self.failure=str(error) if isinstance(error,ProfileError) else 'profile_storage_unsafe'
        if self.store:self.memory_observer.start();atexit.register(self.memory_observer.close)
        self.project=state/"note.txt"
        if self.store and not self.project.exists():self.project.write_text("sample project "+owner+"\n"+secrets.token_hex(12)+"\n")
    def record_stderr(self, stream):
        # Never retain raw Chromium logs: URLs and user content may appear there.
        patterns={b'No space left on device':'temporary_storage_full',b'Cannot allocate memory':'allocation_failed',
                  b'Out of memory':'allocation_failed',b'pthread_create':'thread_creation_failed',
                  b'FATAL:':'browser_fatal',b'Received signal 5':'renderer_signal_5'}
        for line in iter(lambda:stream.readline(8192),b''):
            for token,code in patterns.items():
                if token in line and code not in self.diagnostics:
                    self.diagnostics.append(code)
                    try:save('browser-diagnostics.json',{'observed_at':int(time.time()),'codes':list(self.diagnostics)})
                    except OSError:pass
        stream.close()
    def data(self):
        result={"owner":owner,"host":socket.gethostname(),"granted":False,"browser":bool(chrome_pids()),"receipt":None,
                "diagnostics":list(self.diagnostics),"memory":memory_snapshot(),
                "sandbox":self.sandbox if self.browser and self.browser.poll() is None else None,
                "profile":self.store.status if self.store else "blocked",
                "startup_error":self.failure,"profile_persistent":bool(self.store),
                "profile_lock_recovered":bool(self.store and self.store.recovered_lock),"browser_close":self.last_close}
        try:
            if self.failure:return result
            self.store.validate()
            consent=state/"consent.json"
            if consent.exists() or consent.is_symlink():
                regular(consent)
                value=json.loads(consent.read_text())
                if value!={"owner":owner,"kind":"local-fictional-consent"}:raise ProfileError('profile_owner_mismatch')
                result['granted']=True
            receipt=state/"receipt.json"
            if receipt.exists() or receipt.is_symlink():
                regular(receipt);result['receipt']=json.loads(receipt.read_text())
        except (ProfileError,OSError,ValueError) as error:
            self.failure=str(error) if isinstance(error,ProfileError) else 'profile_storage_unsafe'
            result.update(granted=False,startup_error=self.failure,profile='blocked')
        return result
    def close(self):
        managed=bool(self.browser)
        if self.browser:
            graceful=False
            if self.browser.poll() is None:
                try:graceful=close_windows(self.browser.pid)
                except (OSError,ValueError):pass
                if not graceful:self.browser.terminate()
                try:self.browser.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    graceful=False
                    try:os.killpg(self.browser.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    self.browser.wait()
            else:graceful=False
            self.last_close='graceful' if graceful and self.browser.returncode==0 else 'forced_or_unexpected'
            self.browser=None
        if managed:
            for pid in chrome_pids():
                try:os.kill(pid,signal.SIGKILL)
                except ProcessLookupError:pass
        end=time.monotonic()+2
        while managed and chrome_pids() and time.monotonic()<end:time.sleep(.05)
        if self.diagnostic_reader:self.diagnostic_reader.join(timeout=.5)
        self.desktop.close();self.path=""
    def expire(self,expected):
        with self.lock:
            if self.path!=expected:return
            if self.browser is None or self.browser.poll() is not None or self.desktop.expired():self.close();return
            timer=threading.Timer(10,self.expire,args=(expected,));timer.daemon=True;timer.start()
    def act(self,body):
        with self.lock:
            op=body["op"]
            current=self.data()
            if current['startup_error'] and op not in ('status','close-browser'):
                raise ValueError(current['startup_error'])
            if op in ("begin","open-browser"):
                target=body.get('url')
                if not target:
                    target=self.target if self.browser and self.browser.poll() is None else ('about:blank' if op=='open-browser' else self.target)
                parsed=urlsplit(target or '')
                official=os.environ.get('CPA_PROVIDER')=='claude-subscription'
                allowed=(parsed.scheme=='https' and parsed.netloc=='claude.ai' if official else parsed.scheme=='http' and parsed.netloc==owner.lower()+'.upstream.invalid:8080')
                blank_reentry=op=='open-browser' and not body.get('url') and target=='about:blank'
                if not blank_reentry and (not allowed or parsed.path!='/oauth/authorize' or parsed.username is not None):
                    raise ValueError('authorization_url_rejected')
                self.target=target
                if self.browser is None or self.browser.poll() is not None:
                    self.close();self.seen.clear();self.ack.clear();self.consent.clear();self.diagnostics=[]
                    self.path="/"+secrets.token_hex(18)
                    binaries=[p for p in Path("/ms-playwright").glob("chromium-*/**/chrome") if p.is_file()]
                    if not binaries:raise ValueError("chromium_missing")
                    self.store.before_open(bool(chrome_pids()))
                    self.desktop.env['HOME']=str(self.store.home)
                    self.desktop.start()
                    self.browser=subprocess.Popen([str(binaries[0]),"--ozone-platform=x11","--lang=en-US","--start-maximized","--disable-dev-shm-usage","--disable-background-networking","--disable-crash-reporter","--no-first-run","--proxy-server=socks5://127.0.0.1:1080","--proxy-bypass-list=localhost;127.0.0.1;[::1]","--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1, EXCLUDE [::1]","--window-size=1100,760","--user-data-dir="+str(self.store.profile),self.target],env=self.desktop.env,start_new_session=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
                    self.diagnostic_reader=threading.Thread(target=self.record_stderr,args=(self.browser.stderr,),daemon=True);self.diagnostic_reader.start()
                    time.sleep(.2)
                    if self.browser.poll() is not None:
                        self.close();raise ValueError("browser_start_failed")
                    try:self.sandbox=wait_for_sandbox(self.browser)
                    except (OSError,ValueError):
                        self.close();raise ValueError("browser_sandbox_unavailable")
                    timer=threading.Timer(10,self.expire,args=(self.path,));timer.daemon=True;timer.start()
                else:
                    restore_browser(self.browser.pid)
                return dict(self.data(),desktop_session=self.desktop.session,desktop_pass=self.desktop.password)
            elif op=="restore-browser":
                if self.browser is None or self.browser.poll() is not None:raise ValueError("browser_not_running")
                restore_browser(self.browser.pid)
            elif op=="close-browser":
                self.close()
            elif op=="approve" and not (state/"consent.json").exists():
                if not self.browser or not self.seen.is_set():raise ValueError("open_browser_first")
                self.consent.set()
                if not self.ack.wait(5):
                    self.close();raise ValueError("consent_timeout")
                self.close()
                if chrome_pids():raise ValueError("browser_still_open")
                save("consent.json",{"owner":owner,"kind":"local-fictional-consent"})
            elif op=="task":
                if not (state/"consent.json").exists():raise ValueError("consent_required")
                if chrome_pids():raise ValueError("browser_still_open")
                raw=self.project.read_bytes();job=body["job"]
                save("receipt.json",{"owner":owner,"job":job,"host":socket.gethostname(),"lines":len(raw.splitlines()),"file_sha256":hashlib.sha256(raw).hexdigest(),"browser_processes":len(chrome_pids()),"os":Path("/etc/os-release").read_text().split('PRETTY_NAME="')[1].split('"')[0]})
            elif op not in ("status","begin","approve"):raise ValueError("unknown")
            return dict(self.data(),desktop_session=self.desktop.session)

w=Worker()
atexit.register(w.close)
signal.signal(signal.SIGTERM,lambda *_:sys.exit(0))
class Page(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def respond(self,status,body,typ):
        self.send_response(status);self.send_header("Content-Type",typ);self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
    def do_GET(self):
        if not w.path or "Chrome" not in self.headers.get("User-Agent",""):return self.send_error(404)
        if self.path==w.path+"/qr":
            token="CPA-OFFLINE-QR-"+owner
            png=subprocess.check_output(["qrencode","-o","-","-s","8","-m","4",token])
            html=("<!doctype html><meta charset=utf-8><title>QR "+owner+"</title><h2>Offline QR "+owner+"</h2>"
                  "<img alt='Offline QR' src='data:image/png;base64,"+base64.b64encode(png).decode()+"'>")
            self.respond(200,html.encode(),"text/html; charset=utf-8");return
        if self.path==w.path:
            granted=(state/"consent.json").exists()
            heading="Authorization saved" if granted else "Waiting for authorization"
            detail="This local test account is ready." if granted else "Confirm this test authorization in the management page."
            page=("<!doctype html><meta charset=utf-8><title>Local account "+owner+"</title>"
                  "<style>body{background:#f0f4f3;color:#193a38;font:20px system-ui;margin:56px}h1{font-size:38px;margin:14px 0}p{margin-top:8px}</style>"
                  "<main>Ubuntu Chromium &nbsp;/&nbsp; Local account "+owner+"<h1>"+heading+"</h1><p>"+detail+"</p></main>"
                  "<p><label>Test input <input id='field' maxlength='512'></label> <button onclick='result.textContent=field.value'>Apply</button> <output id='result'></output></p>"
                  "<p><button onclick=\"window.open(location.pathname+'/qr','qr','width=460,height=460')\">Open QR window</button></p>"
                  "<script>async function check(){let r=await fetch(location.pathname+'/decision');if((await r.text())==='approve'){await fetch(location.pathname+'/accepted',{method:'POST'})}else{setTimeout(check,300)}}check()</script>")
            self.respond(200,page.encode(),"text/html");return
        if self.path==w.path+"/decision":
            w.seen.set();self.respond(200,b"approve" if w.consent.is_set() else b"wait","text/plain");return
        self.send_error(404)
    def do_POST(self):
        if w.path and self.path==w.path+"/accepted" and w.consent.is_set() and "Chrome" in self.headers.get("User-Agent",""):
            self.respond(200,b"ok","text/plain");w.ack.set();return
        self.send_error(404)
class Control(socketserver.StreamRequestHandler):
    def handle(self):
        try:data=w.act(json.loads(self.rfile.readline(2048)))
        except ValueError as e:data={"error":str(e)}
        self.wfile.write(json.dumps(data).encode()+b"\n")
web=http.server.ThreadingHTTPServer(("127.0.0.1",8765),Page)
threading.Thread(target=web.serve_forever,daemon=True).start()
Path(local).unlink(missing_ok=True)
socketserver.UnixStreamServer(local,Control).serve_forever()

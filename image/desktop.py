"""On-demand X11 desktop inside a single network-disabled test container."""
import os
import secrets
import signal
import socket
import string
import subprocess
import time
from pathlib import Path

class Desktop:
    def __init__(self):
        self.processes=[]
        self.env={**os.environ,'DISPLAY':':23','HOME':'/tmp/fixture-desktop','XDG_RUNTIME_DIR':'/tmp/fixture-xdg'}
        self.password=''
        self.session=''
        self.disconnected=0

    def launch(self,*args):
        p=subprocess.Popen(args,env=self.env,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
        self.processes.append(p)
        return p

    def start(self):
        for key in ('HOME','XDG_RUNTIME_DIR'):
            Path(self.env[key]).mkdir(mode=0o700,exist_ok=True)
        self.launch('Xvfb',':23','-screen','0','1100x760x24','-nolisten','tcp','-noreset')
        for _ in range(80):
            try:
                with socket.socket(socket.AF_UNIX) as s:s.connect('/tmp/.X11-unix/X23')
                break
            except OSError:time.sleep(.05)
        else:raise RuntimeError('display_unavailable')
        self.launch('openbox','--sm-disable')
        self.password=''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(8))
        self.session=secrets.token_urlsafe(24)
        path=Path('/tmp/fixture-xdg/vnc.pass')
        path.write_text(self.password+'\n');path.chmod(0o600)
        self.launch('x11vnc','-display',':23','-localhost','-forever','-shared','-passwdfile',str(path),'-rfbport','5901','-noxdamage','-add_keysyms','-quiet')
        self.launch('websockify','--web=/usr/share/novnc','127.0.0.1:6081','127.0.0.1:5901')
        for port in (5901,6081):
            for _ in range(80):
                try:
                    with socket.create_connection(('127.0.0.1',port),timeout=.2):pass
                    break
                except OSError:time.sleep(.05)
            else:raise RuntimeError('desktop_unavailable')
        self.disconnected=time.monotonic()
    def expired(self):
        # An established connection at the RFB server means a viewer is still attached.
        for filename in ('/proc/net/tcp','/proc/net/tcp6'):
            for line in Path(filename).read_text().splitlines()[1:]:
                fields=line.split()
                if fields[1].endswith(':170D') and fields[3]=='01':
                    self.disconnected=time.monotonic()
                    return False
        return time.monotonic()-self.disconnected>=180
    def close(self):
        for p in reversed(self.processes):
            if p.poll() is None:
                try:os.killpg(p.pid,signal.SIGTERM)
                except ProcessLookupError:pass
        for p in self.processes:
            try:p.wait(1)
            except subprocess.TimeoutExpired:
                try:os.killpg(p.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                p.wait()
        self.processes.clear()
        Path('/tmp/fixture-xdg/vnc.pass').unlink(missing_ok=True)
        self.session=self.password=''

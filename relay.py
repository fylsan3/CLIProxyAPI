"""Ephemeral, loopback-only HTTP/WebSocket bridge to an identified offline desktop."""
import contextlib
import os
import re
import secrets
import select
import socket
import socketserver
import subprocess
import threading
from urllib.parse import urlsplit
from pathlib import Path

TUNNEL="""import os,select,socket
with socket.create_connection(('127.0.0.1',6081),timeout=4) as s:
 s.setblocking(True)
 while True:
  ready,_,_=select.select([0,s],[],[],90)
  if not ready:continue
  if 0 in ready:
   b=os.read(0,65536)
   if not b:break
   s.sendall(b)
  if s in ready:
   b=s.recv(65536)
   if not b:break
   while b:b=b[os.write(1,b):]
"""
class Relay(socketserver.ThreadingTCPServer):
    daemon_threads=True
    request_queue_size=64
    def __init__(self,cli,ident,session,guard,restore):
        self.guard=guard
        self.restore=restore
        self.session=session
        self.token=secrets.token_urlsafe(30)
        self.cmd=[*cli,'exec','--user','1001:1001','-i',ident,'python3','-u','-c',TUNNEL]
        self.closed=threading.Event()
        super().__init__(('127.0.0.1',0),Handler)
        self.authority='127.0.0.1:'+str(self.server_address[1])
        self.url='http://'+self.authority+'/'+self.token+'/desktop.html'
        threading.Thread(target=self.serve_forever,kwargs={'poll_interval':.1},daemon=True).start()
    def close(self):
        self.closed.set();self.shutdown();self.server_close()

class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        s=self.request
        try:self.relay(s)
        except (OSError,ValueError,subprocess.SubprocessError):pass
    def relay(self,s):
        server=self.server;s.settimeout(4);buf=b''
        while b'\r\n\r\n' not in buf and len(buf)<16384:
            b=s.recv(4096)
            if not b:return
            buf+=b
        header,sep,body=buf.partition(b'\r\n\r\n')
        if not sep:return
        lines=header.decode('latin1').split('\r\n')
        method,path,version=lines[0].split(' ')
        prefix='/'+server.token+'/'
        headers={k.lower():v.strip() for line in lines[1:] for k,v in [line.split(':',1)]}
        if method=='POST' and path==prefix+'restore-browser':
            valid=(headers.get('host')==server.authority and headers.get('origin')=='http://'+server.authority and
                   headers.get('x-desktop-action')=='restore' and headers.get('content-length','0')=='0' and
                   'transfer-encoding' not in headers and not server.closed.is_set())
            status='403 Forbidden';payload=b'{"error":"restore_denied"}'
            if valid:
                try:
                    server.guard();server.restore();status='200 OK';payload=b'{"restored":true}'
                except (OSError,ValueError,subprocess.SubprocessError):
                    status='503 Service Unavailable';payload=b'{"error":"browser_restore_unavailable"}'
            s.sendall(('HTTP/1.0 '+status+'\r\nContent-Type: application/json\r\nCache-Control: no-store\r\nContent-Length: '+str(len(payload))+'\r\n\r\n').encode()+payload);return
        if method!='GET' or not path.startswith(prefix) or headers.get('host')!=server.authority:
            s.sendall(b'HTTP/1.0 404 Not Found\r\nContent-Length: 0\r\n\r\n');return
        is_ws=headers.get('upgrade','').lower()=='websocket'
        if is_ws and headers.get('origin')!='http://'+server.authority:return
        target=path[len(prefix):]
        if not re.fullmatch(r'[A-Za-z0-9_./-]+',target) or '..' in target.split('/'):return
        if is_ws and target!='websockify':return
        if not is_ws and target=='desktop.html':
            server.guard()
            payload=(Path(__file__).resolve().parent/'ui/desktop.html').read_bytes()
            s.sendall(('HTTP/1.0 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nCache-Control: no-store\r\nReferrer-Policy: no-referrer\r\nX-Content-Type-Options: nosniff\r\nContent-Length: '+str(len(payload))+'\r\n\r\n').encode()+payload);return
        if not is_ws:
            lines=[line for line in lines if not line.lower().startswith('connection:')]
            lines.append('Connection: close')
        lines[0]=method+' /'+target+' '+version
        s.settimeout(10)
        server.guard()
        p=subprocess.Popen(server.cmd,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
        try:
            response_head=b'';head_sent=is_ws
            p.stdin.write(('\r\n'.join(lines)+'\r\n\r\n').encode('latin1')+body);p.stdin.flush()
            while not server.closed.is_set():
                readable,_,_=select.select([s,p.stdout],[],[],1)
                if s in readable:
                    b=s.recv(65536)
                    if not b:break
                    p.stdin.write(b);p.stdin.flush()
                if p.stdout in readable:
                    b=os.read(p.stdout.fileno(),65536)
                    if not b:break
                    if not head_sent:
                        response_head+=b
                        if b'\r\n\r\n' not in response_head:
                            if len(response_head)>65536:raise ValueError('desktop_response_header_too_large')
                            continue
                        raw_head,_,payload=response_head.partition(b'\r\n\r\n')
                        fields=[line for line in raw_head.split(b'\r\n') if not line.lower().startswith((b'connection:',b'keep-alive:'))]
                        b=b'\r\n'.join(fields)+b'\r\nConnection: close\r\n\r\n'+payload
                        head_sent=True;response_head=b''
                    s.sendall(b)
        finally:
            with contextlib.suppress(OSError):p.stdin.close()
            try:p.wait(3)
            except subprocess.TimeoutExpired:p.terminate();p.wait(3)
            p.stdout.close()

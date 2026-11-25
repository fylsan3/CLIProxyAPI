"""Authenticated SOCKS fixture with fixed local name resolution and no internet routes."""
import ipaddress
import json
import os
from pathlib import Path
import select
import socket
import socketserver
import struct
import sys
import threading

sys.path.insert(0, '/opt/native')
from socks_adapter import receive

owner = sys.argv[1]
spec=json.loads(Path('/fixture/accounts.json').read_text())[owner]
Path('/mock/proxy-' + owner + '.pid').write_text(str(os.getpid()))
lock = threading.Lock()


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        conn, remote = self.request, None
        try:
            conn.settimeout(3)
            version, count = receive(conn, 2)
            methods = receive(conn, count)
            if version != 5 or 2 not in methods:
                return
            conn.sendall(b'\x05\x02')
            version, length = receive(conn, 2)
            username = receive(conn, length).decode()
            password = receive(conn, receive(conn, 1)[0]).decode()
            if version != 1 or username != 'test-' + owner or password != 'fixture-password-' + owner:
                conn.sendall(b'\x01\x01')
                return
            conn.sendall(b'\x01\x00')
            if receive(conn, 3) != b'\x05\x01\x00':
                return
            kind = receive(conn, 1)[0]
            if kind == 3:
                host = receive(conn, receive(conn, 1)[0]).decode('ascii')
            elif kind in (1, 4):
                host = str(ipaddress.ip_address(receive(conn, 4 if kind == 1 else 16)))
            else:
                return
            port = struct.unpack('!H', receive(conn, 2))[0]
            allowed=host in ('claude.ai','platform.claude.com','api.anthropic.com','ipwho.is','api.ipify.org','www.cloudflare.com') and port==443
            with lock, Path('/mock/socks-' + owner + '.jsonl').open('a') as out:
                out.write(json.dumps({'proxy':owner,'peer':self.client_address[0],'host':host,'port':port,'remote_domain':kind==3,'allowed':allowed}) + '\n')
            if not allowed:
                conn.sendall(b'\x05\x02\x00\x01' + b'\x00' * 6)
                return
            remote = socket.create_connection(('127.0.0.1', spec['origin_port']), timeout=3)
            conn.sendall(b'\x05\x00\x00\x01' + b'\x00' * 6)
            conn.settimeout(None)
            remote.settimeout(None)
            readers = {conn, remote}
            while readers:
                ready, _, _ = select.select(list(readers), [], [])
                for source in ready:
                    target = remote if source is conn else conn
                    data = source.recv(65536)
                    if not data:
                        readers.remove(source)
                        target.shutdown(socket.SHUT_WR)
                    else:
                        target.sendall(data)
        except (OSError, ValueError):
            pass
        finally:
            if remote:
                remote.close()


with Server(('0.0.0.0', spec['proxy_port']), Handler) as server:
    server.serve_forever()

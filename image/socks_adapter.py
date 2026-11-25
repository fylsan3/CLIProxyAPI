"""Loopback SOCKS adapter: one immutable authenticated upstream, no direct fallback."""
import http.client
import ipaddress
import json
import os
from pathlib import Path
import select
import ssl
import socket
import socketserver
import struct
import threading
import time


def receive(conn, size):
    result = bytearray()
    while len(result) < size:
        piece = conn.recv(size - len(result))
        if not piece:
            raise OSError('socket_closed')
        result.extend(piece)
    return bytes(result)


def address(conn):
    atyp = receive(conn, 1)
    if atyp == b'\x03':
        length = receive(conn, 1)
        host = receive(conn, length[0])
        wire = atyp + length + host
    elif atyp in (b'\x01', b'\x04'):
        wire = atyp + receive(conn, 4 if atyp == b'\x01' else 16)
    else:
        raise ValueError('address_type_invalid')
    return wire + receive(conn, 2)


def domain(host, port):
    encoded = host.encode('idna')
    if not 0 < len(encoded) < 256:
        raise ValueError('domain_invalid')
    return b'\x03' + bytes([len(encoded)]) + encoded + struct.pack('!H', port)


class Adapter:
    def __init__(self, config):
        self.config = config
        ipaddress.ip_address(config['proxy_ip'])
        self.lock = threading.Lock()
        self.active = set()
        self.healthy = False
        self.startup_passed = False
        self.stopping = threading.Event()
        self.last_publish = 0
        self.inflight = 0
        self.check_started = False
        self.check_running = False
        self.check_thread = None
        self.last_success = None
        self.startup_result = {'healthy':False,'reason':'startup_network_pending','check_mode':'startup_only'}
        if config.get('check_mode','fixture') not in ('fixture','https_exit'):
            raise ValueError('invalid_check_mode')

    def connect(self, destination, timeout=.7, track=None):
        # Numeric address prevents a host DNS lookup for the proxy itself.
        conn = socket.create_connection((self.config['proxy_ip'], self.config['proxy_port']), timeout=timeout)
        try:
            if track is not None:track(conn)
            conn.sendall(b'\x05\x01\x02')
            if receive(conn, 2) != b'\x05\x02':
                raise ValueError('proxy_auth_method_rejected')
            user = self.config['username'].encode()
            password = self.config['password'].encode()
            if not 0 < len(user) < 256 or not 0 < len(password) < 256:
                raise ValueError('proxy_credentials_invalid')
            conn.sendall(b'\x01' + bytes([len(user)]) + user + bytes([len(password)]) + password)
            if receive(conn, 2) != b'\x01\x00':
                raise ValueError('proxy_auth_rejected')
            conn.sendall(b'\x05\x01\x00' + destination)
            header = receive(conn, 3)
            if header != b'\x05\x00\x00':
                raise ValueError('proxy_connect_rejected')
            address(conn)
            conn.settimeout(None)
            return conn
        except BaseException:
            conn.close()
            raise

    def acquire_request(self):
        with self.lock:
            if not self.healthy or not 0<=time.monotonic()-self.last_publish<2:return False
            self.inflight+=1
            return True

    def release_request(self):
        with self.lock:self.inflight-=1

    def ready(self):
        with self.lock:
            return self.healthy and 0<=time.monotonic()-self.last_publish<2

    def publish(self):
        # This timestamp is local supervisor liveness, not a new network probe.
        with self.lock:
            self.last_publish=time.monotonic()
            value=dict(self.startup_result,owner=self.config['owner'],checked_at=time.time(),
                       healthy=self.healthy,
                       reason='startup_verified' if self.startup_passed else self.startup_result['reason'],
                       observation_healthy=self.startup_result['healthy'],
                       observation_reason=self.startup_result['reason'],
                       warning=self.startup_passed and not self.startup_result['healthy'],
                       fixed_timezone=self.config.get('timezone'),
                       periodic_network_checks=False,idle_check_interval_seconds=None,
                       checking=self.check_running,active_connections=self.inflight,
                       next_check_in_seconds=None,
                       last_success_at=self.last_success)
        root=Path('/run/network/live');pending=root/'status.pending'
        pending.write_text(json.dumps(value));pending.chmod(0o600);pending.replace(root/'status.json')

    def check_endpoint(self, host, path, kind):
        sockets=[];guard=threading.Lock();expired=threading.Event()
        def track(conn):
            with guard:
                if expired.is_set():conn.close();raise TimeoutError('check_deadline')
                sockets.append(conn)
        def expire():
            with guard:
                expired.set()
                for conn in sockets:
                    try:conn.shutdown(socket.SHUT_RDWR)
                    except OSError:pass
                    conn.close()
        # This limit applies only to network-check traffic, never model streams.
        timer=threading.Timer(20,expire);timer.daemon=True;timer.start()
        conn=None;client=http.client.HTTPConnection(host,timeout=7)
        try:
            conn=self.connect(domain(host,443 if kind!='fixture' else self.config['check_port']),timeout=7,track=track)
            conn.settimeout(7)
            if kind!='fixture':
                conn=ssl.create_default_context().wrap_socket(conn,server_hostname=host)
                track(conn)
            client.sock=conn
            client.request('GET',path,headers={'User-Agent':'CPA-Network-Check/1','Connection':'close'})
            response=client.getresponse();body=response.read(4097)
            if response.status!=200 or len(body)>4096:raise ValueError('exit_service_response_invalid')
            if kind=='fixture':
                value=json.loads(body)
                if value.get('owner')!=self.config['owner']:raise ValueError('exit_owner_mismatch')
                address=value['egress']
            elif kind=='json':address=json.loads(body)['ip']
            else:address=dict(line.split('=',1) for line in body.decode().splitlines() if '=' in line)['ip']
            return str(ipaddress.ip_address(address))
        finally:
            timer.cancel();client.close()
            if conn is not None:conn.close()

    def check_network(self):
        fixture=self.config.get('check_mode','fixture')=='fixture'
        endpoints=[(self.config['check_host'],'/network-check','fixture')] if fixture else [
            ('api.ipify.org','/?format=json','json'),('www.cloudflare.com','/cdn-cgi/trace','trace')]
        value={'healthy':False,'reason':'network_check_failed','check_mode':'startup_only',
               'network_checked_at':time.time(),'periodic_network_checks':False,'services':[]}
        expected=str(ipaddress.ip_address(self.config['expected_egress']))
        for host,path,kind in endpoints:
            try:
                address=self.check_endpoint(host,path,kind)
                value['services'].append({'service':host,'ok':True})
                value['exit_ip']=address
                value['healthy']=address==expected
                value['reason']='network_verified' if value['healthy'] else 'exit_changed'
                # An observed wrong exit must not be hidden by a fallback response.
                break
            except (OSError,ValueError,KeyError,http.client.HTTPException):
                value['services'].append({'service':host,'ok':False})
        # A saved timezone is immutable here. Idle observations only explain drift.
        if self.startup_passed and self.config.get('timezone'):
            value.update(timezone_checked_at=time.time(),timezone_warning=True,timezone_check_reason='timezone_check_failed')
            try:
                from locale_probe import fetch_location
                location=fetch_location(dict(self.config,expected_egress=value.get('exit_ip',expected)))
                value['observed_timezone']=location['timezone']
                value['timezone_warning']=location['timezone']!=self.config['timezone']
                value['timezone_check_reason']='timezone_changed' if value['timezone_warning'] else 'timezone_verified'
            except (OSError,ValueError,KeyError,http.client.HTTPException):pass
        with self.lock:
            self.startup_result=value
            # Only startup admission is a gate. No recurring public probes are scheduled;
            # request failures remain the native CPA executor's responsibility.
            self.startup_passed=self.startup_passed or value['healthy']
            self.healthy=self.startup_passed
            if value['healthy']:self.last_success=time.time()

    def run_check(self):
        try:self.check_network()
        except Exception:
            # Never expose an exception containing proxy parameters.
            with self.lock:
                self.startup_result={'healthy':False,'reason':'network_check_failed',
                                     'check_mode':'startup_only','network_checked_at':time.time(),
                                     'periodic_network_checks':False,'services':[]}
                self.healthy=self.startup_passed
        finally:
            with self.lock:self.check_running=False

    def start_initial_check(self):
        with self.lock:
            if self.check_started:return False
            self.check_started=True
            self.check_running=True
            self.check_thread=threading.Thread(target=self.run_check,daemon=True)
            self.check_thread.start()
            return True

    def monitor(self):
        self.start_initial_check()
        while not self.stopping.is_set():
            self.publish()
            # A slow public checker cannot block the local supervisor heartbeat.
            self.stopping.wait(.5)


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        adapter = self.server.adapter
        remote = None
        local = self.request
        acquired = False
        try:
            acquired=adapter.acquire_request()
            if not acquired:return
            local.settimeout(3)
            version, count = receive(local, 2)
            methods = receive(local, count)
            if version != 5 or 0 not in methods:
                local.sendall(b'\x05\xff')
                return
            local.sendall(b'\x05\x00')
            if receive(local, 3) != b'\x05\x01\x00':
                raise ValueError('only_connect_supported')
            destination = address(local)
            remote = adapter.connect(destination)
            local.sendall(b'\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00')
            local.settimeout(None)
            with adapter.lock:
                adapter.active.update((local, remote))
            # No timeout is placed on an established model or stream connection.
            open_readers = {local, remote}
            while open_readers:
                ready, _, _ = select.select(list(open_readers), [], [])
                for reader in ready:
                    writer = remote if reader is local else local
                    data = reader.recv(65536)
                    if not data:
                        open_readers.remove(reader)
                        writer.shutdown(socket.SHUT_WR)
                    else:
                        writer.sendall(data)
        except (OSError, ValueError):
            pass
        finally:
            with adapter.lock:
                adapter.active.discard(local)
                if remote:
                    adapter.active.discard(remote)
            if remote:
                remote.close()
            if acquired:adapter.release_request()


if __name__ == '__main__':
    os.umask(0o077)
    adapter = Adapter(json.loads(Path('/network-config/config.json').read_text()))
    threading.Thread(target=adapter.monitor, daemon=True).start()
    with Server(('127.0.0.1', 1080), Handler) as server:
        server.adapter = adapter
        server.serve_forever(poll_interval=.1)

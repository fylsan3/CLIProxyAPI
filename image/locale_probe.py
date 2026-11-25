"""Bounded timezone discovery before account storage exists; no direct fallback."""
import http.client
import ipaddress
from account_identity import valid_owner
import json
import ssl
import subprocess
import sys
import socket
import threading
import time
from zoneinfo import ZoneInfo
from socks_adapter import Adapter,domain


def validate_location(value,expected):
    if not isinstance(value,dict) or value.get('success') is not True:raise ValueError('location_unavailable')
    if not isinstance(value.get('ip'),str) or not isinstance(value.get('timezone'),dict):raise ValueError('invalid_location')
    address=str(ipaddress.ip_address(value['ip']))
    if expected is not None and address!=str(ipaddress.ip_address(expected)):raise ValueError('exit_mismatch')
    name=value['timezone']['id']
    if not isinstance(name,str) or len(name)>100:raise ValueError('invalid_timezone')
    ZoneInfo(name)
    return {'exit_ip':address,'timezone':name,'language':'en-US','observed_at':int(time.time())}


def probe(config):
    peer=ipaddress.ip_address(config['proxy_ip']);port=config['proxy_port']
    if type(port) is not int or not 0<port<65536:raise ValueError('invalid_port')
    for version,binary in ((4,'iptables-nft'),(6,'ip6tables-nft')):
        def rule(*args):subprocess.run([binary,'-w','3',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        rule('-P','OUTPUT','DROP');rule('-F','OUTPUT')
        if peer.version==version:rule('-A','OUTPUT','-p','tcp','-d',str(peer),'--dport',str(port),'-j','ACCEPT')
        rule('-A','OUTPUT','-j','DROP')
    return fetch_location(config)


def fetch_location(config):
    fixture=config.get('test_only') is True
    if fixture:
        if not valid_owner(config.get('owner')):raise ValueError('invalid_fixture')
        host=config['owner'].lower()+'.upstream.invalid';destination_port=8080;path='/location-check'
    else:
        host='ipwho.is';destination_port=443;path='/?fields=ip,success,timezone.id'
    adapter=Adapter(config)
    sockets=[];guard=threading.Lock();expired=threading.Event()
    def track(conn):
        with guard:
            if expired.is_set():conn.close();raise TimeoutError('location_deadline')
            sockets.append(conn)
    def expire():
        with guard:
            expired.set()
            for conn in sockets:
                try:conn.shutdown(socket.SHUT_RDWR)
                except OSError:pass
                conn.close()
    timer=threading.Timer(20,expire);timer.daemon=True;timer.start()
    conn=None;client=http.client.HTTPConnection(host,timeout=7)
    try:
        conn=adapter.connect(domain(host,destination_port),timeout=7,track=track)
        conn.settimeout(7)
        if not fixture:
            conn=ssl.create_default_context().wrap_socket(conn,server_hostname=host);track(conn)
        client.sock=conn
        client.request('GET',path,headers={'Accept':'application/json','Connection':'close'})
        response=client.getresponse();raw=response.read(8193)
        if response.status!=200 or len(raw)>8192:raise ValueError('location_response_invalid')
        result=validate_location(json.loads(raw),config['expected_egress'])
        result['source']='fixture' if fixture else 'ipwho.is'
        return result
    finally:
        timer.cancel();client.close()
        if conn is not None:conn.close()


if __name__=='__main__':
    try:print(json.dumps(probe(json.load(sys.stdin))))
    except Exception:raise SystemExit('exit_timezone_unavailable')

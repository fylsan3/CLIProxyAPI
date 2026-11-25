"""Start only local proxy/upstream/DNS sensors on an internal Docker network."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import threading
import time

processes = []
lock = threading.Lock()


def dns_sink(family, tcp):
    sock = socket.socket(family, socket.SOCK_STREAM if tcp else socket.SOCK_DGRAM)
    if family == socket.AF_INET6:
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(('0.0.0.0' if family == socket.AF_INET else '::', 53))
    if tcp:
        sock.listen()
    while True:
        if tcp:
            conn, peer = sock.accept()
            conn.close()
        else:
            data, peer = sock.recvfrom(4096)
            if len(data) >= 12:
                response = data[:2] + b'\x81\x83' + data[4:]
                sock.sendto(response, peer)
        with lock, Path('/mock/dns.jsonl').open('a') as out:
            out.write(json.dumps({'family':family,'tcp':tcp,'peer':peer[0]}) + '\n')


os.umask(0o077)
for family in (socket.AF_INET, socket.AF_INET6):
    for tcp in (False, True):
        threading.Thread(target=dns_sink, args=(family,tcp), daemon=True).start()
for owner in json.loads(Path('/fixture/accounts.json').read_text()):
    for script in ('origin.py', 'socks.py'):
        env = dict(os.environ, FIXTURE_OWNER=owner)
        processes.append(subprocess.Popen(['python3','-B','/fixture/' + script,owner],env=env))
signal.signal(signal.SIGTERM,lambda *_:exit(0))
try:
    while True:
        time.sleep(1)
finally:
    for process in processes:
        if process.poll() is None:
            process.terminate()

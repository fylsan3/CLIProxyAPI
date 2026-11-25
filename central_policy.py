"""Mac process policy for a disposable central CPA with only explicit broker sockets.

This is a process restriction, not a restriction on the machine administrator.
Linux needs separate OS identities and a service-manager deployment review.
"""
import json
from pathlib import Path


def mac_profile(sockets, private_directories, engine, inbound_port=None):
    sockets = [str(Path(path).resolve()) for path in sockets]
    if not sockets or len(set(sockets)) != len(sockets):
        raise ValueError('Explicit distinct broker sockets are required')
    rules = ['(version 1)', '(allow default)', '(deny network*)',
             '(allow network-inbound (local ip "localhost:*"))']
    if inbound_port is not None:
        if type(inbound_port) is not int or not 1024<=inbound_port<=65535:raise ValueError('invalid_production_port')
        rules[3]='(allow network-inbound (local ip "*:'+str(inbound_port)+'"))'
    for path in sockets:
        rules.append('(allow network-outbound (remote unix-socket (literal '+json.dumps(path)+')))')
    for path in [str(Path(engine).resolve()), *[str(Path(p).resolve()) for p in private_directories]]:
        rules.append('(deny file-read* file-write* (subpath '+json.dumps(path)+'))')
    return '\n'.join(rules)

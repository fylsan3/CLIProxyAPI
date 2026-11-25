"""Pre-account bootstrap: install guard, delegate HTTP to Go; no account volumes."""
import ipaddress
import json
import subprocess

def probe(config):
    peer=ipaddress.ip_address(config['proxy_ip']);port=config['proxy_port']
    if type(port) is not int or not 0<port<65536:raise ValueError('invalid_port')
    for version,binary in ((4,'iptables-nft'),(6,'ip6tables-nft')):
        def rule(*args):subprocess.run([binary,'-w','3',*args],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        rule('-P','OUTPUT','DROP');rule('-F','OUTPUT')
        if peer.version==version:
            rule('-A','OUTPUT','-p','tcp','-d',str(peer),'--dport',str(port),'-m','owner','--uid-owner','1002','-j','ACCEPT')
        rule('-A','OUTPUT','-j','DROP')
    command=['setpriv','--reuid=1002','--regid=1002','--clear-groups','--bounding-set=-all',
             '--inh-caps=-all','--ambient-caps=-all','--no-new-privs','/opt/native/worker','network-probe']
    subprocess.run(command,input=json.dumps(config).encode(),check=True,timeout=25)

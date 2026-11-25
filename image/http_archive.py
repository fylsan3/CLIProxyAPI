"""Inspect encrypted HTTP samples, or replay against a server created by this tool.

Replay never connects to the recorded URL. It only connects to its own ephemeral
loopback listener; run it in a network-disabled disposable container for review.
"""
import argparse, hashlib, http.client, http.server, json, os, stat, struct, threading
from pathlib import Path
from urllib.parse import urlsplit
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

SECRET = {'authorization', 'proxy-authorization', 'cookie', 'set-cookie', 'x-api-key'}

def private_file(path):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid!=os.getuid() or info.st_nlink!=1:
        raise ValueError('private_regular_file_required')
    return path.read_bytes()

def decrypt(path,key):
    raw=private_file(path)
    if not raw.startswith(b'CPAENC1\n'):raise ValueError('unknown_archive_format')
    offset=8;out=[];ended=False;aes=AESGCM(key)
    while offset<len(raw):
        if offset+4>len(raw):raise ValueError('truncated_archive')
        length=struct.unpack_from('>I',raw,offset)[0];offset+=4
        if length<28 or length>65564 or offset+length>len(raw) or ended:raise ValueError('invalid_archive_chunk')
        block=raw[offset:offset+length];offset+=length
        clear=aes.decrypt(block[:12],block[12:],path.name.encode())
        if not clear:ended=True
        else:out.append(clear)
    if not ended:raise ValueError('archive_final_record_missing')
    return b''.join(out)

def load_exchange(folder,key):
    if folder.is_symlink() or not folder.is_dir():raise ValueError('archive_directory_required')
    request=json.loads(decrypt(folder/'request.json.enc',key));response=json.loads(decrypt(folder/'response.json.enc',key))
    if any(meta.get('archive_id')!=folder.parent.name or meta.get('exchange')!=folder.name for meta in (request,response)):raise ValueError('archive_binding_changed')
    bodies=[]
    for kind,meta in [('request',request),('response',response)]:
        body=decrypt(folder/(kind+'.bin.enc'),key)
        if not meta.get('complete') or len(body)!=meta.get('bytes') or hashlib.sha256(body).hexdigest()!=meta.get('sha256'):
            raise ValueError('incomplete_or_changed_'+kind)
        bodies.append(body)
    if not request.get('write_succeeded') or not request.get('wire_headers'):raise ValueError('request_write_not_verified')
    if request.get('write_attempts',1)!=1:raise ValueError('multiple_transport_attempts_need_separate_review')
    if response.get('uncompressed_by_transport'):raise ValueError('transport_decoded_body_not_wire_encoded')
    return request,response,*bodies

def pairs(groups):
    return [(item['name'],value) for item in groups for value in item['values']]

def normalized(values):
    out={}
    for name,value in values:out.setdefault(name.lower(),[]).append(value)
    return out

def inspect(folder,key):
    request,response,body,reply=load_exchange(folder,key)
    def safe(name,value):
        lower=name.lower()
        return '[REDACTED]' if lower in SECRET or any(x in lower for x in ('token','secret','session','device-id','request-id')) else value
    return {'complete':True,'method':request['method'],'request_header_names':[k for k,v in pairs(request['wire_headers'])],
            'request_headers':[(k,safe(k,v)) for k,v in pairs(request['wire_headers'])],
            'request_bytes':len(body),'response_status':response['status'],
            'response_headers':[(k,safe(k,v)) for k,values in response['headers'].items() for v in values],
            'response_bytes':len(reply),'response_trailer_names':list(response.get('trailers') or {}),
            'raw_sensitive_values_retained_encrypted':True,'tls_and_packet_boundaries_preserved':False}

def replay(folder,key):
    request,response,body,reply=load_exchange(folder,key)
    target=urlsplit(request['url']);path=target.path or '/'
    if target.query:path+='?'+target.query
    received={}
    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version='HTTP/1.1'
        def log_message(self,*args):pass
        def do_GET(self):self.handle_sample()
        def do_POST(self):self.handle_sample()
        def handle_sample(self):
            self.close_connection=True
            trailers=[]
            if self.headers.get('Transfer-Encoding','').lower()=='chunked':
                chunks=[]
                while True:
                    n=int(self.rfile.readline().split(b';')[0],16)
                    if n==0:
                        while True:
                            line=self.rfile.readline()
                            if line==b'\r\n':break
                            name,value=line.decode('latin1').split(':',1);trailers.append((name,value.strip()))
                        break
                    chunks.append(self.rfile.read(n));assert self.rfile.read(2)==b'\r\n'
                raw=b''.join(chunks)
            else:raw=self.rfile.read(int(self.headers.get('Content-Length','0')))
            received.update(method=self.command,path=self.path,headers=list(self.headers.raw_items()),body=raw,trailers=trailers)
            self.send_response_only(response['status'])
            for name,values in response['headers'].items():
                for value in values:self.send_header(name,value)
            chunked='chunked' in (response.get('transfer_encoding') or [])
            if chunked:self.send_header('Transfer-Encoding','chunked')
            self.end_headers()
            if chunked:
                if reply:self.wfile.write(('%x\r\n'%len(reply)).encode()+reply+b'\r\n')
                self.wfile.write(b'0\r\n')
                for name,values in (response.get('trailers') or {}).items():
                    for value in values:self.wfile.write((name+': '+value+'\r\n').encode('latin1'))
                self.wfile.write(b'\r\n')
            else:self.wfile.write(reply)
    server=http.server.HTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.handle_request,daemon=True);thread.start()
    c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=15)
    try:
        # Host and authentication values go only to this in-process fixture.
        c.putrequest(request['method'],path,skip_host=True,skip_accept_encoding=True)
        header_pairs=pairs(request['wire_headers'])
        for name,value in header_pairs:c.putheader(name,value)
        c.endheaders()
        if 'chunked' in (request.get('transfer_encoding') or []):
            if body:c.send(('%x\r\n'%len(body)).encode()+body+b'\r\n')
            c.send(b'0\r\n')
            for name,values in (request.get('trailers') or {}).items():
                for value in values:c.send((name+': '+value+'\r\n').encode('latin1'))
            c.send(b'\r\n')
        elif body:c.send(body)
        result=c.getresponse();got=result.read();thread.join(5)
        expected_headers=normalized(header_pairs)
        expected_response=normalized([(k,v) for k,values in response['headers'].items() for v in values])
        if 'chunked' in (response.get('transfer_encoding') or []):expected_response['transfer-encoding']=['chunked']
        checks={'request_method_match':received.get('method')==request['method'],'request_path_query_match':received.get('path')==path,
                'request_headers_match':normalized(received.get('headers',[]))==expected_headers,'request_body_match':received.get('body')==body,
                'request_trailers_match':normalized(received.get('trailers',[]))==normalized([(k,v) for k,values in (request.get('trailers') or {}).items() for v in values]),
                'response_status_match':result.status==response['status'],'response_headers_match':normalized(result.getheaders())==expected_response,'response_body_match':got==reply}
        if not all(checks.values()):raise ValueError('replay_comparison_failed: '+json.dumps(checks))
        return dict(checks,target='self_created_loopback_fixture',real_provider_contacted=False,original_credentials_sent_to_provider=False)
    finally:c.close();server.server_close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['inspect','replay']);p.add_argument('--exchange',type=Path,required=True);p.add_argument('--key-file',type=Path,required=True);a=p.parse_args()
    try:
        key=private_file(a.key_file)
        result=inspect(a.exchange,key) if a.action=='inspect' else replay(a.exchange,key)
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except Exception as error:
        # Never print decrypted data through exception representations.
        print(json.dumps({'error':'archive_validation_or_replay_failed','error_type':type(error).__name__}));raise SystemExit(1)

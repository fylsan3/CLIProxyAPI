"""One-shot private HTTP recording and exact-body replay into a closed test CPA.

The recorder is a temporary loopback entry, not a global production logger.
Authentication headers are forwarded live but never persisted or reused.
"""
import argparse,contextlib,gzip,hashlib,http.client,http.server,json,os,secrets,select,socket,stat,threading,time
from pathlib import Path
from urllib.parse import urlsplit

SECRET={'authorization','proxy-authorization','x-api-key','cookie','set-cookie'}
HOP={'connection','keep-alive','proxy-authenticate','proxy-authorization','te','trailer','transfer-encoding','upgrade','content-length','host','expect'}
MARKER='X-CPA-Sample'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def safe_headers(headers,record=False):
    pairs=list(headers.items()) if hasattr(headers,'items') else list(headers)
    connection={n.strip().lower() for k,v in pairs if k.lower()=='connection' for n in v.split(',')}
    denied=HOP|connection|{MARKER.lower()}
    if record:denied|=SECRET
    return [(k,v) for k,v in pairs if k.lower() not in denied]

def private_dir(path):
    path=Path(path)
    if path.is_symlink():raise ValueError('symlink_rejected')
    path.mkdir(mode=0o700,parents=True,exist_ok=True)
    info=path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid!=os.getuid() or stat.S_IMODE(info.st_mode)!=0o700:raise ValueError('private_directory_required')
    return path

def write_private(path,raw):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())

def read_private(path):
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_mode&0o077:raise ValueError('private_regular_file_required')
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW),'rb') as f:return f.read()

def target_url(value):
    u=urlsplit(value)
    if u.scheme!='http' or u.hostname!='127.0.0.1' or not u.port or u.username or u.path not in ('','/') or u.query or u.fragment:
        raise ValueError('explicit_loopback_http_target_required')
    return u

def request_body(h,stream):
    lengths=h.get_all('Content-Length',[]);enc=h.get_all('Transfer-Encoding',[])
    if enc:
        if lengths or len(enc)!=1 or enc[0].lower()!='chunked':raise ValueError('ambiguous_request_framing')
        chunks=[]
        while True:
            line=stream.readline(4097)
            if not line.endswith(b'\r\n') or len(line)>4096:raise ValueError('invalid_chunk')
            size=int(line.split(b';')[0],16)
            if size<0:raise ValueError('invalid_chunk')
            if size==0:
                # No trailers are silently discarded: exact functional replay
                # cannot be guaranteed if clients submit request trailers.
                if stream.readline(4097)!=b'\r\n':raise ValueError('request_trailers_unsupported')
                return b''.join(chunks)
            data=stream.read(size)
            if len(data)!=size or stream.read(2)!=b'\r\n':raise ValueError('short_chunk')
            chunks.append(data)
    if len(lengths)!=1:raise ValueError('content_length_required')
    size=int(lengths[0])
    if size<0:raise ValueError('invalid_length')
    raw=stream.read(size)
    if len(raw)!=size:raise ValueError('short_request')
    return raw

class Recording:
    def __init__(self,root,marker,ttl=2700):
        self.root=private_dir(root);self.marker=marker;self.expiry=time.monotonic()+ttl;self.lock=threading.Lock();self.claimed=False
    def claim(self,marker):
        with self.lock:
            if self.claimed or time.monotonic()>self.expiry or not secrets.compare_digest(marker.encode('utf-8'),self.marker.encode('utf-8')):return None
            self.claimed=True
            folder=self.root/('sample-'+secrets.token_hex(12))
            try:folder.mkdir(mode=0o700)
            except OSError:return None
            return folder

class CaptureServer(http.server.ThreadingHTTPServer):
    daemon_threads=False
    def __init__(self,target,recording):
        self.target=target_url(target);self.recording=recording
        super().__init__(('127.0.0.1',0),CaptureHandler)

class CaptureHandler(http.server.BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    def log_message(self,*args):pass
    def do_POST(self):
        self.close_connection=True # A one-shot diagnostic entry must not leave idle handler threads.
        u=urlsplit(self.path)
        if u.scheme or u.netloc or u.path not in ('/v1/messages','/v1/messages/count_tokens'):
            self.send_error(404);return
        try:raw=request_body(self.headers,self.rfile)
        except (OSError,ValueError):self.send_error(400);self.close_connection=True;return
        folder=self.server.recording.claim(self.headers.get(MARKER,''))
        record={'schema':1,'source':'captured_http_request','path':self.path,'method':'POST','request_complete':True,
                'request_sha256':sha(raw),'request_bytes':len(raw),'request_headers':safe_headers(self.headers,True),
                'omitted_request_header_names':sorted({k for k in self.headers.keys() if k.lower() in SECRET}),
                'transfer_framing_preserved':False,'content_encoding_preserved':True,'response_complete':False,'captured_at':time.time()}
        if folder:
            try:write_private(folder/'request.bin',raw)
            except OSError:folder=None
        target=self.server.target;conn=http.client.HTTPConnection(target.hostname,target.port,timeout=10)
        stop_watch=threading.Event();watch=None
        sent=False;response_digest=hashlib.sha256();response_size=0;response_file=None
        try:
            conn.connect();conn.sock.settimeout(None) # No model execution/read deadline.
            upstream_socket=conn.sock
            def cancel_on_disconnect():
                while not stop_watch.wait(.2):
                    try:
                        ready,_,_=select.select([self.connection],[],[],0)
                        if ready and self.connection.recv(1,socket.MSG_PEEK)==b'':
                            with contextlib.suppress(OSError):upstream_socket.shutdown(socket.SHUT_RDWR)
                            return
                    except OSError:
                        with contextlib.suppress(OSError):upstream_socket.shutdown(socket.SHUT_RDWR)
                        return
            watch=threading.Thread(target=cancel_on_disconnect,daemon=True);watch.start()
            conn.putrequest('POST',self.path,skip_accept_encoding=True)
            for k,v in safe_headers(self.headers):conn.putheader(k,v)
            conn.putheader('Content-Length',str(len(raw)));conn.endheaders(raw)
            response=conn.getresponse();record.update(status=response.status,response_headers=safe_headers(response.headers,True))
            if folder:
                try:response_file=os.fdopen(os.open(folder/'response.bin',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600),'wb')
                except OSError:folder=None
            self.send_response_only(response.status)
            for k,v in safe_headers(response.headers):self.send_header(k,v)
            self.send_header('Transfer-Encoding','chunked');self.send_header('Connection','close');self.end_headers();sent=True
            while True:
                chunk=response.read1(65536)
                if not chunk:break
                response_digest.update(chunk);response_size+=len(chunk)
                if response_file:
                    try:response_file.write(chunk)
                    except OSError:
                        with contextlib.suppress(OSError):response_file.close()
                        response_file=None;folder=None
                self.wfile.write(('%x\r\n'%len(chunk)).encode()+chunk+b'\r\n');self.wfile.flush()
            if response.length not in (None,0):raise http.client.IncompleteRead(b'',response.length)
            record['response_complete']=True
            self.wfile.write(b'0\r\n\r\n');self.wfile.flush()
        except (OSError,http.client.HTTPException):
            record['failure']='transfer_incomplete';self.close_connection=True
            if not sent:
                with contextlib.suppress(OSError):self.send_error(502,'local transfer failed')
        finally:
            stop_watch.set()
            if watch:watch.join(1)
            conn.close()
            if response_file:
                try:response_file.flush();os.fsync(response_file.fileno())
                except OSError:folder=None
                finally:
                    with contextlib.suppress(OSError):response_file.close()
            record.update(response_sha256=response_digest.hexdigest(),response_bytes=response_size)
            if folder:
                with contextlib.suppress(OSError):write_private(folder/'record.json',json.dumps(record,ensure_ascii=False,indent=2).encode())

def closed_test_target(state):
    state=Path(state).resolve();launch=json.loads(read_private(state/'launch.json'))
    fixture=json.loads(read_private(state/'broker-private/network-fixture.json'))
    if fixture.get('mode') not in ('closed_test','closed_tls_test') or not launch.get('ephemeral'):
        raise ValueError('ephemeral_closed_test_state_required')
    u=urlsplit(launch['api_base']);target=target_url('http://'+u.netloc)
    key_path=Path(launch['api_key_file']).resolve()
    if key_path!=state/'client-key':raise ValueError('test_key_must_belong_to_state')
    key=read_private(key_path).decode().strip()
    if len(key)!=48:raise ValueError('invalid_test_key')
    return target,key

def replay(sample,state,output):
    sample=private_dir(sample);record=json.loads(read_private(sample/'record.json'));raw=read_private(sample/'request.bin')
    if record.get('schema')!=1 or record.get('source')!='captured_http_request' or not record.get('request_complete') or sha(raw)!=record['request_sha256'] or len(raw)!=record['request_bytes']:
        raise ValueError('incomplete_or_changed_request')
    path=record['path'];u=urlsplit(path)
    if u.scheme or u.netloc or u.path not in ('/v1/messages','/v1/messages/count_tokens'):raise ValueError('invalid_replay_path')
    target,key=closed_test_target(state);output=private_dir(output)
    if (output/'replay.json').exists():raise ValueError('replay_output_exists')
    conn=http.client.HTTPConnection(target.hostname,target.port,timeout=10)
    try:
        conn.connect();conn.sock.settimeout(None)
        conn.putrequest('POST',path,skip_accept_encoding=True)
        for k,v in safe_headers(record['request_headers'],True):conn.putheader(k,v)
        conn.putheader('Authorization','Bearer '+key);conn.putheader('Content-Length',str(len(raw)));conn.endheaders(raw)
        response=conn.getresponse();body=response.read()
        write_private(output/'response.bin',body)
        result={'request_body_unchanged':sha(raw)==record['request_sha256'],'request_sha256':sha(raw),'status':response.status,
                'response_sha256':sha(body),'response_headers':safe_headers(response.headers,True),
                'substitutions':['destination','authentication','HTTP transfer framing'],'original_credentials_reused':False,
                'historical_response_match':bool(record.get('response_complete') and sha(body)==record.get('response_sha256'))}
        write_private(output/'replay.json',json.dumps(result,indent=2).encode());return result
    finally:conn.close()

def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='action',required=True)
    c=sub.add_parser('capture');c.add_argument('--target',required=True);c.add_argument('--directory',type=Path,required=True);c.add_argument('--ttl',type=int,default=2700)
    q=sub.add_parser('replay');q.add_argument('--sample',type=Path,required=True);q.add_argument('--test-state',type=Path,required=True);q.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.action=='replay':print(json.dumps(replay(a.sample,a.test_state,a.output),indent=2));return
    if not 1<=a.ttl<=2700:raise ValueError('ttl_must_be_between_1_and_2700')
    recording=Recording(a.directory,secrets.token_urlsafe(24),a.ttl);server=CaptureServer(a.target,recording)
    write_private(recording.root/'capture-entry.json',json.dumps({'url':'http://127.0.0.1:'+str(server.server_port),'marker_header':MARKER,'marker':recording.marker,'expires_in_seconds':a.ttl}).encode())
    timer=threading.Timer(a.ttl,server.shutdown);timer.daemon=True;timer.start()
    print('Temporary capture entry written to '+str(recording.root/'capture-entry.json')+'; no global logging changed.',flush=True)
    try:server.serve_forever(poll_interval=.1)
    finally:timer.cancel();server.server_close()
if __name__=='__main__':main()

"""Loopback management for the isolated fake-account candidate only."""
import hmac
import http.server
import json
import secrets
import threading
from pathlib import Path

ROOT=Path(__file__).resolve().parent

class Panel(http.server.ThreadingHTTPServer):
    daemon_threads=True

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*unused):pass
    def reply(self,status,body,kind):
        self.send_response(status)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(body)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers();self.wfile.write(body)
    def do_POST(self):
        origin='http://127.0.0.1:'+str(self.server.server_port)
        if self.headers.get('Host')!=origin[7:] or self.headers.get('Origin')!=origin:
            return self.reply(403,b'{}','application/json')
        if not hmac.compare_digest(self.headers.get('X-Offline-View','').encode(),self.server.token.encode()):
            return self.reply(401,b'{}','application/json')
        if self.path!='/action':return self.reply(404,b'{}','application/json')
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=4096:raise ValueError('invalid_request')
            self.connection.settimeout(4)
            body=json.loads(self.rfile.read(length))
            from dashboard import action
            status,result=action(self.server.broker,body)
            return self.reply(status,json.dumps(result).encode(),'application/json')
        except (ValueError,KeyError):return self.reply(400,b'{"error":"invalid_request"}','application/json')
        except Exception:return self.reply(503,b'{"error":"operation_unavailable"}','application/json')
    def do_GET(self):
        if self.headers.get('Host')!='127.0.0.1:'+str(self.server.server_port):
            return self.reply(403,b'{}','application/json')
        if self.path=='/snapshot':
            supplied=self.headers.get('X-Offline-View','')
            if not hmac.compare_digest(supplied.encode(),self.server.token.encode()):return self.reply(401,b'{}','application/json')
            try:
                from dashboard import snapshot
                result=snapshot(self.server.broker)
                return self.reply(200,json.dumps(result).encode(),'application/json')
            except Exception:return self.reply(503,b'{"error":"status_unavailable"}','application/json')
        files={'/':('index.html','text/html; charset=utf-8'),'/creation.js':('creation.js','text/javascript; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/settings.js':('settings.js','text/javascript; charset=utf-8'),'/quota_view.js':('quota_view.js','text/javascript; charset=utf-8'),'/style.css':('style.css','text/css; charset=utf-8')}
        files.update({'/xterm.js':('vendor/xterm.js','text/javascript; charset=utf-8'),'/xterm.css':('vendor/xterm.css','text/css; charset=utf-8'),'/claude_code.js':('claude_code.js','text/javascript; charset=utf-8'),'/claude_code.css':('claude_code.css','text/css; charset=utf-8'),'/metrics.js':('metrics.js','text/javascript; charset=utf-8')})
        if self.path not in files:return self.reply(404,b'{}','application/json')
        name,kind=files[self.path];self.reply(200,(ROOT/'ui'/name).read_bytes(),kind)


def start_panel(broker,port):
    server=Panel(('127.0.0.1',port),Handler);server.broker=broker;server.token=secrets.token_urlsafe(32)
    record=broker.folder/'status-page.json'
    record.write_text(json.dumps({'url':'http://127.0.0.1:'+str(server.server_port)+'/#'+server.token,'offline_only':True}))
    record.chmod(0o600)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    return server,record

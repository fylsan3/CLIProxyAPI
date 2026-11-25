"""Local-only visual acceptance fixture; never forwards write requests."""
import copy,http.client,http.server,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
MODE=ROOT/'evidence/ui-preview-mode'
actions=[];registered=[];logging=True

def snapshot():
    sample={'providers':{'claude':{'label':'Claude 订阅通道'}},'runtime_mode':'closed_test','logging_to_file':logging,'release':{'candidate':'界面演示 · 虚构账号'},'refresh_workers':16,'projects':[],'requests':[]}
    base={'provider':'claude','container':'fake-container-123456','overall_ready':True,'reason':'account_ready','central_dispatch':{'reason':'eligible'},'network':{'healthy':True,'fixed_timezone':'Asia/Tokyo'},'protection':{'phase':'ready','backup_verified':True,'initial_backup':True},'state':{'authorized':True,'active_calls':2,'revision':4,'renewal_state':'renewal_verified'},'attempts':[],'portable_backup':{'state':'exported','revision':4,'exported_at':1795575600},'usage':{'totals':{'input_tokens':1280,'output_tokens':320},'attempt_counts':{'confirmed':3,'partial':0,'unreported':0,'invalid':0}}}
    a=copy.deepcopy(base);a.update(slug='research-a',label='研发账号 A')
    b=copy.deepcopy(base);b.update(slug='research-b',label='研发账号 B · 待授权',overall_ready=False,reason='authorization_pending',state={'active_calls':0,'revision':0,'authorized':False},protection={'phase':'authorizing','backup_verified':False,'initial_backup':True},central_dispatch={'reason':'unavailable'})
    mode=MODE.read_text().strip() if MODE.exists() else 'populated'
    if mode=='populated':sample['projects']=[a,b]
    if mode.startswith('creation-'):
        a.update(overall_ready=False,reason='missing',container=None,state=None,network=None,protection={'phase':'creating','backup_verified':False,'creation_steps':[{'step':'checking_socks','status':'completed','started_at':1795590000},{'step':'checking_exit','status':'running','started_at':1795590001}]})
        if mode=='creation-error':a['protection'].update(phase='creation_failed',creation_error='proxy_auth_rejected',creation_steps=[{'step':'checking_socks','status':'failed','started_at':1795590000}])
        sample['projects']=[a]
    if mode=='long':a['label']='跨区域研发账号与自动化任务测试环境—这是一个特别长的显示名称';sample['projects']=[a,b]
    sample['projects']+=registered
    return sample

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def send(self,code,data,kind='application/json'):
        if not isinstance(data,bytes):data=json.dumps(data,ensure_ascii=False).encode()
        self.send_response(code);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data)
    def do_GET(self):
        path=self.path.split('?')[0]
        if path in ('/','/accounts.html','/management.html'):return self.send(200,(ROOT/'static/management.local.html').read_bytes(),'text/html; charset=utf-8')
        if path=='/viewer-demo.html':return self.send(200,'<h1>虚构浏览器窗口</h1><p>仅验证入口，没有真实账号。</p>'.encode(),'text/html; charset=utf-8')
        if path=='/v8/management/account-environments/snapshot':
            if MODE.exists() and MODE.read_text().strip()=='error':return self.send(503,{'error':'fixture_unavailable'})
            return self.send(200,snapshot())
        if path=='/preview-actions':return self.send(200,actions)
        if path.startswith('/v8/management/'):
            connection=http.client.HTTPConnection('127.0.0.1',8317,timeout=5)
            try:
                connection.request('GET',self.path,headers={'Authorization':self.headers.get('Authorization','')});response=connection.getresponse();self.send(response.status,response.read(),response.getheader('Content-Type','application/json'))
            finally:connection.close()
            return
        self.send(404,{})
    def do_POST(self):
        global logging
        if self.path!='/v8/management/account-environments/action':return self.send(405,{})
        value=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))));actions.append({k:v for k,v in value.items() if k!='proxy_url'});action=value.get('action')
        if action=='register':registered.append({'slug':value['slug'],'label':value['label'],'provider':value['provider'],'reason':'missing','overall_ready':False,'protection':{'phase':'not_created'},'attempts':[]});return self.send(200,{'ok':True})
        if action=='proxy-view':return self.send(200,{'proxy_url':'socks5h://fictional-user:fictional-password@192.0.2.10:1080'})
        if action=='logging-update':logging=value['value'];return self.send(200,{'ok':True})
        if action in ('open-browser','auth-begin'):return self.send(200,{'viewer_url':'http://127.0.0.1:'+str(self.server.server_port)+'/viewer-demo.html'})
        return self.send(200,{'ok':True})

if __name__=='__main__':
    server=http.server.ThreadingHTTPServer(('127.0.0.1',int(sys.argv[1]) if len(sys.argv)>1 else 18319),Handler)
    print('Local UI fixture: http://127.0.0.1:'+str(server.server_port)+'/accounts.html',flush=True);server.serve_forever()

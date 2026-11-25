"""Persistent account metadata; never stores provider tokens or proxy passwords."""
import json,os,sys,threading,time
from pathlib import Path
from account_identity import valid_slug,owner_for
sys.path.insert(0,str(Path(__file__).resolve().parent/'image'))
from retention import read_json,write_json,private

PROVIDERS={'mock-claude':{'label':'Claude 模拟服务','offline_only':True,'models':['test-project-shared']},'claude-subscription':{'label':'Claude 订阅通道','offline_only':False,'models':[m['id'] for m in json.loads((Path(__file__).resolve().parent/'models.json').read_text())]}}

class Registry:
    def __init__(self,folder):
        self.folder=Path(folder);private(self.folder,directory=True)
        self.path=self.folder/'accounts.json';self.lock=threading.RLock()
        if not self.path.exists() and not self.path.is_symlink():
            if any((self.folder/'environments').glob('*.json')):
                raise ValueError('account_registry_missing_no_reset')
            write_json(self.path,{'schema':1,'accounts':[]})
        self.read()
    def read(self):
        with self.lock:
            data=read_json(self.path)
            if not isinstance(data,dict) or set(data)!={'schema','accounts'} or data['schema']!=1 or not isinstance(data['accounts'],list):
                raise ValueError('account_registry_invalid')
            seen=set()
            for row in data['accounts']:
                if not isinstance(row,dict) or set(row)!={'slug','owner','label','provider','created_at'}:raise ValueError('account_registry_invalid')
                self.validate(row['slug'],row['label'],row['provider'])
                if row['owner']!=owner_for(row['slug']) or row['slug'] in seen or type(row['created_at']) is not int:raise ValueError('account_registry_invalid')
                seen.add(row['slug'])
            return data
    @staticmethod
    def validate(slug,label,provider):
        owner_for(slug)
        if not isinstance(label,str) or not 1<=len(label)<=60 or label!=label.strip() or any(ord(c)<32 or ord(c)==127 for c in label):
            raise ValueError('invalid_account_label')
        if not isinstance(provider,str) or provider not in PROVIDERS:raise ValueError('provider_not_available')
    def list(self):return self.read()['accounts']
    def get(self,slug):
        owner_for(slug)
        for row in self.list():
            if row['slug']==slug:return row
        raise ValueError('account_not_registered')
    def owners(self):return [row['owner'] for row in self.list()]
    def register(self,slug,label,provider):
        self.validate(slug,label,provider)
        with self.lock:
            data=self.read()
            for row in data['accounts']:
                if row['slug']==slug:
                    if row['label']==label and row['provider']==provider:return row
                    raise ValueError('account_already_registered')
            row=dict(slug=slug,owner=owner_for(slug),label=label,provider=provider,created_at=int(time.time()))
            data['accounts'].append(row);write_json(self.path,data);return row

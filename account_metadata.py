"""Non-secret account identity and route settings; immutable container ownership."""
import hashlib,json,threading,time,uuid
from pathlib import Path
from retention import read_json,write_json

class Metadata:
    def __init__(self,folder):
        self.path=Path(folder)/'account-metadata.json';self.lock=threading.RLock()
        if not self.path.exists():write_json(self.path,{'schema':1,'identities':{},'routes':{}})
    def read(self):
        data=read_json(self.path)
        if data.get('schema')!=1 or not isinstance(data.get('identities'),dict) or not isinstance(data.get('routes'),dict):raise ValueError('account_metadata_invalid')
        return data
    def bind(self,slug,identity):
        if not identity or not identity.get('key'):return None
        key=identity['key'];email=identity.get('email','')
        if not isinstance(key,str) or len(key)!=64 or any(c not in '0123456789abcdef' for c in key):raise ValueError('account_identity_invalid')
        if not isinstance(email,str) or len(email)>254 or any(ord(c)<32 for c in email):raise ValueError('account_identity_invalid')
        with self.lock:
            data=self.read();items=data['identities'];old=items.get(slug)
            if old and old['key']!=key:raise ValueError('account_environment_rebind_denied')
            if any(s!=slug and item['key']==key for s,item in items.items()):raise ValueError('account_already_bound')
            new={'key':key,'email':email or (old or {}).get('email','')}
            if new!=old:items[slug]=new;write_json(self.path,data)
            return new
    def identity(self,slug):
        with self.lock:return self.read()['identities'].get(slug)
    def route(self,slug):
        with self.lock:return self.read()['routes'].get(slug,{'priority':0,'weight':1,'revision':0})
    def patch_route(self,slug,changes,expected=None):
        if not changes or set(changes)-{'priority','weight'}:raise ValueError('invalid_route_fields')
        for k,v in changes.items():
            if type(v) is not int or (k=='weight' and not 0<=v<=1000000) or (k=='priority' and not -(2**31)<=v<2**31):raise ValueError('invalid_route_value')
        with self.lock:
            data=self.read();old=data['routes'].get(slug,{'priority':0,'weight':1,'revision':0})
            if expected is not None and expected!=old['revision']:raise ValueError('route_revision_conflict')
            new=dict(old,**changes)
            if new!=old:new['revision']+=1;data['routes'][slug]=new;write_json(self.path,data)
            return new

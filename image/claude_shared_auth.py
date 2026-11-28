"""Read Go's committed account snapshot; never refresh or write credentials."""
import json,os,stat,time
from dataclasses import dataclass,field
from datetime import datetime
from pathlib import Path

AUTH_FILE=Path('/state/native-auth.json')

@dataclass(frozen=True)
class Snapshot:
    access_token:str=field(repr=False)
    revision:int
    expires_at:float
    requires_sign_in:bool=False

    def public(self):
        return {'ready':True,'source':'go','refresh_owner':'go','revision':self.revision,
                'expires_at':self.expires_at,'requires_sign_in':self.requires_sign_in,
                'remaining_seconds':max(0,int(self.expires_at-time.time()))}

def private_json(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_nlink!=1 or info.st_mode&0o077:
            raise ValueError('shared_auth_file_unsafe')
        with os.fdopen(fd,'rb',closefd=False) as f:data=f.read(1048577)
        if len(data)>1048576:raise ValueError('shared_auth_file_unsafe')
        value=json.loads(data)
        if not isinstance(value,dict):raise ValueError('shared_auth_invalid')
        return value
    finally:os.close(fd)

def snapshot(config_dir=None):
    try:
        value=private_json(AUTH_FILE)
    except FileNotFoundError:raise ValueError('go_authorization_required') from None
    except (OSError,UnicodeError,json.JSONDecodeError):raise ValueError('shared_auth_unavailable') from None
    if value.get('owner')!=os.environ.get('FIXTURE_OWNER') or not value.get('owner'):
        raise ValueError('shared_auth_account_mismatch')
    token=value.get('token');revision=value.get('revision')
    if not isinstance(token,dict) or type(revision)!=int or revision<0:raise ValueError('shared_auth_invalid')
    access=token.get('access_token')
    if not isinstance(access,str) or not access or len(access)>32768 or any(ord(c)<33 or ord(c)>126 for c in access):
        raise ValueError('shared_auth_invalid')
    try:
        expiry=datetime.fromisoformat(token['expired'].replace('Z','+00:00'))
        if expiry.tzinfo is None:raise ValueError()
        expires=expiry.timestamp()
    except (KeyError,TypeError,AttributeError,ValueError):raise ValueError('shared_auth_expiry_unknown') from None
    auth=value.get('auth') or {};renewal=value.get('renewal') or {}
    if not isinstance(auth,dict) or not isinstance(renewal,dict):raise ValueError('shared_auth_invalid')
    metadata=auth.get('metadata') or {}
    if not isinstance(metadata,dict) or ('access_token' in metadata and metadata['access_token']!=access):
        raise ValueError('shared_auth_record_mismatch')
    if auth.get('disabled') or auth.get('status')=='disabled':raise ValueError('go_account_disabled')
    if renewal.get('rejected_access_token')==access:raise ValueError('shared_access_token_rejected')
    if expires<=time.time():raise ValueError('waiting_for_go_refresh')
    # Do not silently adopt, erase or refresh an older independent CLI login.
    if config_dir:
        saved=Path(config_dir)/'.credentials.json'
        if saved.exists() or saved.is_symlink():
            try:stored=private_json(saved)
            except (OSError,UnicodeError,json.JSONDecodeError):raise ValueError('separate_claude_login_present') from None
            if stored.get('claudeAiOauth'):raise ValueError('separate_claude_login_present')
    return Snapshot(access,revision,expires,bool(renewal.get('requires_sign_in')))

def status(config_dir=None):
    try:return snapshot(config_dir).public()
    except ValueError as error:return {'ready':False,'source':'go','refresh_owner':'go','error':str(error)}

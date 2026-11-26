"""Build the export snapshot from Go's sole policy source; no runtime source edits."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def load_policy():
 source=(ROOT/'src/internal/accountheaders/policy.go').read_text()
 raw=re.search(r'const PolicyJSON = `([^`]+)`',source).group(1)
 return json.loads(raw),hashlib.sha256(raw.encode()).hexdigest()

def resolve(doc,name,os_name='Linux',arch='arm64',seen=()):
 if name in seen:raise ValueError('cyclic_header_profile')
 p=doc['profiles'][name]
 r=resolve(doc,p['extends'],os_name,arch,seen+(name,)) if p.get('extends') else {'set':{},'delete':[]}
 for key,value in p.get('set',{}).items():
  for k,v in dict(doc['variables'],platform_os=os_name,platform_arch=arch).items():value=value.replace('${'+k+'}',v)
  if '${' in value:raise ValueError('unresolved_header_variable')
  r['set'][key]=value
 if 'delete' in p:r['delete']=p['delete'][:]
 for k in r['delete']:r['set'].pop(k,None)
 if 'close' in p:r['close']=p['close']
 return r

def snapshot():
 doc,digest=load_policy();values={}
 for name in doc['profiles']:
  for os_name in ('Linux','MacOS','Windows','Unknown'):
   for arch in ('arm64','x64','x32','arm','Unknown'):
    for key,value in resolve(doc,name,os_name,arch)['set'].items():values.setdefault(key,set()).add(value)
 return {'schema':1,'policy_version':doc['version'],'policy_sha256':digest,'paths':[op['path'] for op in doc['operations']],'header_values':{k:sorted(v) for k,v in sorted(values.items())}}

def generate(check=False):
 path=ROOT/'image/account_header_policy.json';value=json.dumps(snapshot(),indent=2)+'\n'
 if check:
  if not path.exists() or path.read_text()!=value:raise ValueError('generated_export_policy_stale; run build.py')
 else:path.write_text(value)

if __name__=='__main__':generate()

"""HTTP-hop and credential boundaries; never rewrites message bodies or identity."""
import json
from pathlib import Path
POLICY=json.loads((Path(__file__).resolve().parent/'header-policy.json').read_text())

def cooldown_receipt_headers(headers):
 """Only relay bounded scheduling receipts on the private worker/central hop."""
 import re
 names={'x-offline-cooldown-bridge','x-offline-retry-at','x-offline-credential-scope','x-offline-transient-rate-limit'}
 values={}
 for name,items in headers.items():
  lower=name.lower()
  if lower not in names:continue
  if lower in values or not isinstance(items,list) or len(items)!=1 or not isinstance(items[0],str):return {}
  values[lower]=items[0]
 if values.get('x-offline-cooldown-bridge')!='1':return {}
 for key in ('x-offline-credential-scope','x-offline-transient-rate-limit'):
  if values.get(key) not in ('true','false'):return {}
 if 'x-offline-retry-at' in values and not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z',values['x-offline-retry-at']):return {}
 return {name:[value] for name,value in values.items()}

def request_headers(headers):
 scoped={x.strip().lower() for value in headers.get_all('Connection',[]) for x in value.split(',')}
 blocked=set(POLICY['request_blocked'])|scoped
 return {name:headers.get_all(name) for name in headers.keys() if name.lower() not in blocked and not any(name.lower().startswith(p) for p in POLICY['request_internal_prefixes'])}

def response_headers(headers):
 scoped={x.strip().lower() for name,values in headers.items() if name.lower()=='connection' for value in values for x in value.split(',')}
 blocked={x.lower() for x in POLICY['response_blocked']}|scoped
 return {name:values[:] for name,values in headers.items() if name.lower() not in blocked and not any(name.lower().startswith(p) for p in POLICY['response_internal_prefixes'])}

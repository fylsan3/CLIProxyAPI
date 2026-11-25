"""HTTP-hop and credential boundaries; never rewrites message bodies or identity."""
import json
from pathlib import Path
POLICY=json.loads((Path(__file__).resolve().parent/'header-policy.json').read_text())

def request_headers(headers):
 scoped={x.strip().lower() for value in headers.get_all('Connection',[]) for x in value.split(',')}
 blocked=set(POLICY['request_blocked'])|scoped
 return {name:headers.get_all(name) for name in headers.keys() if name.lower() not in blocked and not any(name.lower().startswith(p) for p in POLICY['request_internal_prefixes'])}

def response_headers(headers):
 scoped={x.strip().lower() for name,values in headers.items() if name.lower()=='connection' for value in values for x in value.split(',')}
 blocked={x.lower() for x in POLICY['response_blocked']}|scoped
 return {name:values[:] for name,values in headers.items() if name.lower() not in blocked and not any(name.lower().startswith(p) for p in POLICY['response_internal_prefixes'])}

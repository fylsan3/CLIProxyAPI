"""Conservative derived fixtures. Originals and capture keys never leave account storage.
Free text, unknown fields, tool names/arguments and identifiers are pseudonymized.
Derived fixtures preserve structure, not original byte-level replay semantics.
"""
import gzip,hashlib,hmac,json,os,re,zlib
from pathlib import Path
from urllib.parse import urlsplit,parse_qsl
import http_archive
import field_provenance

SAFE_KEYS=set('model messages system tools metadata role content type text name input id tool_use_id tool_result is_error stop_reason stop_sequence usage input_tokens output_tokens cache_creation_input_tokens cache_read_input_tokens event index delta message error code status request_id program grant_id cedar_ember grants eligible ineligible_reason at_limit next_grant_id weekly_resets_at cooldown_until label resets_total resets_left starts_at ends_at clears paused usable_now use_requires_limit percent_used five_hour seven_day seven_day_overage_included utilization resets_at subscription_type rate_limit_tier organization account uuid email refresh_token access_token expires_in token_type scope stream max_tokens temperature top_p input_schema properties required additionalProperties description signature thinking partial_json'.split())
ENUMS=set('user assistant system text image tool_use tool_result message message_start message_delta message_stop content_block_start content_block_delta content_block_stop text_delta input_json_delta thinking_delta signature_delta end_turn tool_use max_tokens stop_sequence error ping api_error rate_limit_error authentication_error permission_error overloaded_error reset already_used not_limited cooldown ineligible unavailable cedar_ember five_hour seven_day seven_day_overage_included'.split())
SAFE_HEADERS={'user-agent','content-type','accept','accept-encoding','content-encoding','connection','anthropic-version','anthropic-beta','x-app','anthropic-dangerous-direct-browser-access','x-stainless-os','x-stainless-arch','x-stainless-runtime','x-stainless-runtime-version','x-stainless-lang','x-stainless-package-version','x-stainless-retry-count','x-stainless-timeout','cache-control','transfer-encoding','retry-after','retry-after-ms'}
# Preserve only reviewed protocol/environment values, never arbitrary strings in known headers.
# Header-name safety is independent of the sending policy: no policy may expose
# credentials, cookies, identifiers, or arbitrary unknown header values.
POLICY=json.loads(Path(__file__).with_name('account_header_policy.json').read_text())
PROTOCOL_VALUES={'content-type':{'application/json','text/event-stream'},'content-encoding':{'gzip','br','zstd','deflate'},'transfer-encoding':{'chunked'}}
HEADER_VALUES={k:set(v) for k,v in POLICY['header_values'].items() if k in SAFE_HEADERS}
for _name,_values in PROTOCOL_VALUES.items():HEADER_VALUES.setdefault(_name,set()).update(_values)

PATHS=set(POLICY['paths'])
class Sanitizer:
 def __init__(self,key=None):self.key=key or os.urandom(32)
 def token(self,v):return 'redacted_'+hmac.new(self.key,str(v).encode(),hashlib.sha256).hexdigest()[:16]
 def tree(self,v,key=''):
  if isinstance(v,dict):return {(k if k in SAFE_KEYS else self.token(k)):self.tree(x,k) for k,x in v.items()}
  if isinstance(v,list):return [self.tree(x,key) for x in v]
  if isinstance(v,str):return v if key in ('role','type','stop_reason','code','program','clears') and v in ENUMS else self.token(v)
  if key in ('id','uuid','request_id','grant_id','email','access_token','refresh_token'):return self.token(v)
  return v
 def headers(self,rows):
  return [{'name':k,'values':[v if k.lower() in SAFE_HEADERS and v in HEADER_VALUES.get(k.lower(),set()) else self.token(v) for v in vs]} for k,vs in rows]
 def body(self,raw,headers):
  encoding=next((vs[0] for k,vs in headers.items() if k.lower()=='content-encoding' and vs),'')
  try:
   if encoding=='gzip':raw=gzip.decompress(raw)
   elif encoding=='deflate':raw=zlib.decompress(raw)
   elif encoding=='br':
    import brotli;raw=brotli.decompress(raw)
   elif encoding=='zstd':
    import zstandard;raw=zstandard.ZstdDecompressor().decompress(raw,max_output_size=128*1024*1024)
   elif encoding:raise ValueError('unsupported encoding')
   text=raw.decode('utf-8')
   if not text:return {'format':'empty'}
   try:return {'format':'json','value':self.tree(json.loads(text))}
   except json.JSONDecodeError:pass
   if text.startswith(('event:','data:')):
    lines=[]
    for line in text.splitlines():
     if line.startswith('event:'):lines.append('event: '+(line[6:].strip() if line[6:].strip() in ENUMS else self.token(line[6:])))
     elif line.startswith('data:'):
      value=line[5:].strip()
      try:lines.append('data: '+json.dumps(self.tree(json.loads(value)),ensure_ascii=False))
      except json.JSONDecodeError:lines.append('data: '+('[DONE]' if value=='[DONE]' else self.token(value)))
     elif line:lines.append(self.token(line))
     else:lines.append('')
    return {'format':'sse','lines':lines}
   return {'format':'opaque_redacted','value':self.token(raw)}
  except Exception:return {'format':'encoded_or_binary_redacted','value':self.token(raw)}
 def header_comparison(self,q):
  before=q.get('before_override')
  if before is None:return {'available':False,'reason':'historical_capture_without_before_snapshot'}
  def normalized(rows):
   out={}
   for k,vs in rows:out.setdefault(k.lower(),[]).extend(vs)
   return out
  initial=normalized(before['headers'].items())
  assigned=normalized(q['headers'].items())
  wire=normalized((row['name'],row['values']) for row in q['wire_headers'])
  def differences(left,right):
   result=[]
   for k in sorted(left.keys()|right.keys()):
    if left.get(k)==right.get(k):continue
    result.append({'name':k,'action':'added' if k not in left else 'removed' if k not in right else 'replaced',
     'before':self.headers([(k,left.get(k,[]))])[0]['values'],
     'after':self.headers([(k,right.get(k,[]))])[0]['values']})
   return result
  return {'available':True,'boundary':'executor_before_final_header_policy',
   'before_headers':self.headers(list(before['headers'].items())),
   'after_policy_headers':self.headers(list(q['headers'].items())),
   'policy_changes':differences(initial,assigned),'transport_changes':differences(assigned,wire),
   'close_before':before['close'],'close_after':q['close']}
 def exchange(self,folder,key):
  q,r,body,reply=http_archive.load_exchange(folder,key,allow_incomplete=True);u=urlsplit(q['url'])
  path=u.path if u.path in PATHS else '/redacted-endpoint'
  return {'schema':1,'source':'captured_then_sanitized','sample_id':folder.parent.name+'-'+folder.name,'exact_original_replay':False,
   'export_policy':{'version':POLICY['policy_version'],'sha256':POLICY['policy_sha256']},
   'capture_policy':{'version':q.get('policy_version'),'sha256':q.get('policy_sha256')},
   'completeness':{'request':bool(q.get('complete')),'response':bool(r.get('complete')),'original_full_replay_eligible':bool(q.get('complete') and r.get('complete'))},
   'header_comparison':self.header_comparison(q),
   'field_provenance':field_provenance.export(folder,key,body,self),
   'http_end_reason':r.get('end_reason','historical_not_recorded'),
   'request':{'method':q['method'],'host':u.hostname if u.hostname in ('api.anthropic.com','platform.claude.com') else 'fixture.invalid','path':path,
    'query':[[k,v] if k in ('cedar_ember','skip_spend') and v=='1' else [self.token(k),self.token(v)] for k,v in parse_qsl(u.query)],
    'headers':self.headers([(x['name'],x['values']) for x in q['wire_headers']]),'body':self.body(body,q['headers']),
    'trailers':self.headers(list((q.get('trailers') or {}).items()))},
   'response':{'status':r['status'],'headers':self.headers(list(r['headers'].items())),'body':self.body(reply,r['headers']),
    'trailers':self.headers(list((r.get('trailers') or {}).items()))}}
def export(root,only=None,skip=None):
 root=Path(root);key=http_archive.private_file(root/'http-capture.key');s=Sanitizer(hmac.new(key,b'sanitized-fixture-v1',hashlib.sha256).digest());out=[];pending=[]
 for sample in sorted((root/'http-samples').iterdir()):
  if only is not None and sample.name not in only:continue
  for folder in sorted(sample.iterdir()):
   if not folder.is_dir():continue
   if skip is not None and sample.name+'-'+folder.name in skip:continue
   try:out.append(s.exchange(folder,key))
   except Exception:pending.append({'sample_id':sample.name+'-'+folder.name,'status':'incomplete_or_unreadable'})
 return {'samples':out,'pending':pending,'scope':'go_account_http_only','browser_captured':False,'credentials_exported':False}
if __name__=='__main__':
 try:print(json.dumps(export('/state'),ensure_ascii=False))
 except Exception:print('{"error":"sample_export_failed"}');raise SystemExit(1)

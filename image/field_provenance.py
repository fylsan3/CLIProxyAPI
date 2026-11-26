"""Compare recorded boundaries; export paths and keyed tokens, never raw values.
Client/NewAPI origin is not inferred from worker ingress. Historical captures
without snapshots remain explicitly unavailable.
"""
import base64,hashlib,json
import http_archive

KEYS=set('system messages metadata user_id device_id account_uuid session_id model tools name description input_schema properties required type text role content input id tool_use_id tool_result is_error thinking signature max_tokens stream temperature top_p betas cache_control ttl output_config effort context_management'.split())
MISSING=object()

def compare(left,right,sanitizer,limit=4096):
    changes=[];visited=0;truncated=False
    def token(x):
        return None if x is MISSING else sanitizer.token(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')))
    def walk(a,b,path):
        nonlocal visited,truncated
        visited+=1
        if visited>limit:truncated=True;return
        if a is not MISSING and b is not MISSING and type(a)==type(b) and a==b:return
        if isinstance(a,dict) and isinstance(b,dict):
            for k in sorted(a.keys()|b.keys()):
                label=k if k in KEYS else sanitizer.token(k)
                walk(a.get(k,MISSING),b.get(k,MISSING),path+'/'+label)
        elif isinstance(a,list) and isinstance(b,list):
            for i in range(max(len(a),len(b))):walk(a[i] if i<len(a) else MISSING,b[i] if i<len(b) else MISSING,path+'/'+str(i))
        elif path.endswith('/metadata/user_id') and isinstance(a,str) and isinstance(b,str):
            try:
                x,y=json.loads(a),json.loads(b)
                if not isinstance(x,dict) or not isinstance(y,dict):raise ValueError()
                walk(x,y,path+'/$json')
            except ValueError:changes.append({'path':path,'action':'changed','before':token(a),'after':token(b)})
        else:changes.append({'path':path,'action':'added' if a is MISSING else 'removed' if b is MISSING else 'changed','before':token(a),'after':token(b)})
    walk(left,right,'')
    return {'changes':changes,'truncated':truncated,'equal':not changes and not truncated}

def snapshot(path,key,archive,stage):
    value=json.loads(http_archive.decrypt(path,key))
    if value.get('archive_id')!=archive or value.get('stage')!=stage:raise ValueError('snapshot_binding_mismatch')
    raw=base64.b64decode(value['body'],validate=True)
    if hashlib.sha256(raw).hexdigest()!=value.get('sha256'):raise ValueError('snapshot_digest_mismatch')
    return value,raw

def export(folder,key,final_body,sanitizer):
    ingress=folder.parent/'ingress.json.enc';native=folder/'native-request.json.enc'
    if not ingress.exists():return {'available':False,'reason':'ingress_not_recorded','client_origin':'not_observed'}
    entry,raw=snapshot(ingress,key,folder.parent.name,'worker_ingress')
    delivery=folder.parent/'worker-return.json.enc'
    if not delivery.exists():raise ValueError('worker_return_pending')
    returned=json.loads(http_archive.decrypt(delivery,key))
    if returned.get('archive_id')!=folder.parent.name:raise ValueError('return_binding_mismatch')
    result={'available':False,'client_origin':'not_observed','ingress_boundary':'worker_before_native_CPA',
            'worker_return':{k:returned.get(k) for k in ('boundary','bytes','status','write_failed','handler_completed','context_cancelled','client_delivery')}}
    links=entry.get('links') or {}
    def same(a,b):return a==b if a and b else None
    result['routing_checks']={'central_ingress_equals_broker_bytes':same(links.get('central_ingress'),links.get('broker_ingress')),
        'broker_forward_equals_worker_bytes':same(links.get('broker_forward'),hashlib.sha256(raw).hexdigest()),
        'broker_bytes_reserialized':None if not links.get('broker_ingress') else links['broker_ingress']!=hashlib.sha256(raw).hexdigest()}
    result['correlation']={k:sanitizer.token(links[k]) for k in ('run','attempt') if links.get(k)}
    if not native.exists():result['reason']='native_prepared_body_unavailable';return result
    _,prepared=snapshot(native,key,folder.parent.name,'native_prepared')
    try:
        initial,middle,final=[json.loads(x) for x in (raw,prepared,final_body)]
    except (ValueError,UnicodeError):result['reason']='body_not_json';return result
    result.update(available=True,worker_to_native=compare(initial,middle,sanitizer),native_to_wire=compare(middle,final,sanitizer),
                  native_wire_bytes_equal=prepared==final_body,
                  stages={name:sanitizer.tree(value) for name,value in [('worker_ingress',initial),('native_prepared',middle)]})
    return result

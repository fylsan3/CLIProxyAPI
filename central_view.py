"""Read-only central eligibility projection; uses only the isolated launch credential."""
import http.client,json
from pathlib import Path
from account_identity import valid_slug

def central_request(path,action,body):
    if action not in ('pool','refresh','refresh-all','logging-status','logging-update'):raise ValueError('invalid_central_action')
    target=json.loads(Path(path).read_text())
    port=target['port'];key=target['key']
    if not isinstance(port,int) or not 1<=port<=65535 or not isinstance(key,str) or len(key)!=48:raise ValueError('invalid_central_target')
    conn=http.client.HTTPConnection('127.0.0.1',port,timeout=40 if action!='pool' else 10)
    try:
        if action.startswith('logging-'):
            if action=='logging-update' and (set(body)!={'value'} or type(body['value']) is not bool):raise ValueError('invalid_logging_value')
            conn.request('GET' if action=='logging-status' else 'PUT','/v8/management/config/observability/logs/logging-to-file',None if action=='logging-status' else json.dumps(body['value']),{'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        else:
            conn.request('POST','/v8/management/test-projects/'+action,json.dumps(body),{'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        response=conn.getresponse();raw=response.read(262145)
        if len(raw)>262144:raise ValueError('oversized_central_status')
        value=json.loads(raw)
        if action=='logging-status' and response.status==404:
            conn.request('GET','/v0/management/logging-to-file',headers={'Authorization':'Bearer '+key})
            response=conn.getresponse();value=json.loads(response.read(262145))
            return response.status,value
        if action=='logging-status' and response.status==200:value={'logging-to-file':value}
        return response.status,value
    finally:conn.close()

def merge_central(result,central):
    available=bool(central and central.get('started'))
    rows={row['slug']:row.get('dispatch') for row in central.get('accounts',[]) if valid_slug(row.get('slug'))} if available else {}
    for project in result['projects']:
        view=rows.get(project['slug'])
        project['container_ready']=project['ready']
        project['central_dispatch']=view or {'reason':'unknown','eligible':None}
        project['overall_ready']=bool(project['ready'] and view and view.get('eligible') is True)
    result['central_status_available']=available
    result['refresh_workers']=central.get('refresh_workers') if available else None
    result['scheduler_config']=central.get('scheduler_config') if available else None
    result['scheduler_in_flight']=central.get('in_flight') if available else None
    return result

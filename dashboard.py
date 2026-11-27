"""The shared authenticated management contract for the offline account broker."""

from account_identity import valid_slug
import json,sqlite3
from sample_status import capture_summary

def capture_monitor_account(broker,project):
    try:
        record=json.loads((broker.folder.parent/'capture-monitor.json').read_text())
        account=record.get('accounts',{}).get(project['slug'].upper(),{})
        environment=project.get('protection',{}).get('environment_id')
        if not environment or account.get('environment_id')!=environment:return {}
        return account
    except (OSError,ValueError,TypeError):return {}

def capture_reviews(broker,project):
    try:
        account=capture_monitor_account(broker,project)
        archive=project.get('state',{}).get('capture_audit',{}).get('last_archive')
        return {k:v for k,v in account.get('latest_response_reviews',{}).items() if archive and k.startswith(archive+'-')}
    except (OSError,ValueError,TypeError):return {}

def capture_issue_status(broker,project):
    account=capture_monitor_account(broker,project)
    audit=project.get('state',{}).get('capture_audit',{})
    # A stale monitor cannot certify a newer archive. capture_summary filters
    # every sample by the live archive ID, including expected exchange IDs.
    return capture_summary(audit,account.get('latest_response_reviews',{}),account.get('capture_issue_history',[]),account.get('latest_expected_samples',[]))

def snapshot(broker):
    _, result = broker.admin('list', {})
    try:result['resource_monitor']=broker.resources.snapshot() if getattr(broker,'resources',None) else None
    except (OSError,ValueError,sqlite3.Error):result['resource_monitor']=None
    for project in result['projects']:
        from action_trace import latest
        project['last_account_update']=latest(broker.folder,project['slug'])
        project['response_reviews']=capture_reviews(broker,project)
        project['capture_status']=capture_issue_status(broker,project)
        identity=project.get('identity')
        if identity and identity.get('email'):project['label']=identity['email']
        _, history = broker.admin('history', {'slug': project['slug']})
        project['attempts'] = history['attempts'][:5]
        project['portable_backup']=broker.packages.status(project['slug'].upper())
        _, project['usage'] = broker.admin('usage', {'slug': project['slug']})
        _, project['statistics'] = broker.admin('account-statistics', {'slug': project['slug']})
        try:project['activity']=broker.activity(project['slug'].upper()) if hasattr(broker,'activity') else None
        except (OSError,ValueError,sqlite3.Error):project['activity']=None
        project['resource_sample']=(result.get('resource_monitor') or {}).get('accounts',{}).get(project['slug'].upper())
    _, reconciliation = broker.admin('reconcile', {})
    result['requests'] = reconciliation['requests']
    result['offline_only'] = broker.offline_only
    _, result['summary'] = broker.admin('summary', {})
    for project in result['projects']:
        project['last_success_at']=result['summary']['last_success'].get(project['slug'].upper())
    result['summary'].pop('last_success',None)
    return broker.dashboard(result)


def action(broker, body):
    if not isinstance(body, dict):
        return 400, {'error': 'invalid_request'}
    operation = body.get('action')
    if operation == 'logging-update':
        if set(body) != {'action', 'value'} or type(body['value']) is not bool:
            return 400, {'error': 'invalid_request'}
        return broker.admin(operation, {'value': body['value']})
    if operation=='register-auto':
        if set(body)!={'action','provider'}:return 400,{'error':'invalid_request'}
        return broker.admin(operation,{'provider':body['provider']})
    if operation=='register':
        if set(body)!={'action','slug','label','provider'}:return 400,{'error':'invalid_request'}
        try:return broker.admin('register',{k:body[k] for k in ('slug','label','provider')})
        except ValueError as error:
            known={'invalid_account_id','invalid_account_label','provider_not_available','account_already_registered'}
            return 400,{'error':str(error) if str(error) in known else 'invalid_request'}
    allowed = {'create', 'restart', 'auth-begin', 'auth-cancel', 'auth-refresh',
               'retry-backup', 'open-browser', 'close-browser', 'backup-export', 'backup-restore','proxy-view','account-update'}
    expected = {'action', 'slug', 'proxy_url'} if operation == 'create' else {'action', 'slug'}
    if operation not in allowed or set(body) != expected or not valid_slug(body.get('slug')):
        return 400, {'error': 'invalid_request'}
    args = {'slug': body['slug']}
    if operation == 'create':
        from proxy_config import parse_proxy
        try:
            parse_proxy(body['proxy_url'])
        except (ValueError, TypeError):
            return 400, {'error': 'invalid_proxy_config'}
        args['proxy_url'] = body['proxy_url']
    try:broker.registry.get(body['slug'])
    except ValueError:return 400,{'error':'account_not_registered'}
    try:
        if operation=='account-update':
            from action_trace import tracking,stage
            with tracking(broker,body['slug'],operation) as trace:
                try:
                    code,result=broker.admin(operation,args)
                    observation=result.get('account_observation',{})
                    stage('controller_response',status=code,ok=result.get('ok') is True,partial=result.get('partial') is True,
                          attempted_at=observation.get('attempted_at'),archive_id=observation.get('capture',{}).get('id'))
                    return code,dict(result,operation_id=trace['operation_id'],receipt_save_failed=trace.get('receipt_save_failed',False))
                except Exception:
                    stage('controller_failed');raise
        return broker.admin(operation,args)
    except ValueError as error:
        known={'container_unavailable','browser_sandbox_unavailable','browser_start_failed','authorization_url_rejected','browser_restore_unavailable','browser_operation_failed','account_busy','account_maintenance','authorization_pending'}
        if str(error) in known:return 409,{'error':str(error)}
        raise

"""The shared authenticated management contract for the offline account broker."""

from account_identity import valid_slug

def snapshot(broker):
    _, result = broker.admin('list', {})
    for project in result['projects']:
        _, history = broker.admin('history', {'slug': project['slug']})
        project['attempts'] = history['attempts'][:5]
        project['portable_backup']=broker.packages.status(project['slug'].upper())
        _, project['usage'] = broker.admin('usage', {'slug': project['slug']})
    _, reconciliation = broker.admin('reconcile', {})
    result['requests'] = reconciliation['requests']
    result['offline_only'] = broker.offline_only
    return broker.dashboard(result)


def action(broker, body):
    if not isinstance(body, dict):
        return 400, {'error': 'invalid_request'}
    operation = body.get('action')
    if operation == 'logging-update':
        if set(body) != {'action', 'value'} or type(body['value']) is not bool:
            return 400, {'error': 'invalid_request'}
        return broker.admin(operation, {'value': body['value']})
    if operation=='register':
        if set(body)!={'action','slug','label','provider'}:return 400,{'error':'invalid_request'}
        try:return broker.admin('register',{k:body[k] for k in ('slug','label','provider')})
        except ValueError as error:
            known={'invalid_account_id','invalid_account_label','provider_not_available','account_already_registered'}
            return 400,{'error':str(error) if str(error) in known else 'invalid_request'}
    allowed = {'create', 'restart', 'auth-begin', 'auth-cancel', 'auth-refresh',
               'retry-backup', 'open-browser', 'close-browser', 'backup-export', 'backup-restore','proxy-view'}
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
    return broker.admin(operation, args)

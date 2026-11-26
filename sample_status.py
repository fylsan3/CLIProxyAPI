"""Classify sanitized observations without changing capture/replay evidence."""
import json

def response_review(sample):
    completeness=sample.get('completeness',{})
    result={'http_response':'complete' if completeness.get('response') else 'end_unconfirmed',
            'http_request':'complete' if completeness.get('request',True) else 'end_unconfirmed',
            'model_response':'not_observed','client_delivery':'not_observed',
            'original_full_replay_eligible':bool(completeness.get('original_full_replay_eligible'))}
    result['decode_errors']={}
    for side in ('request','response'):
        body=sample.get(side,{}).get('body',{})
        if body.get('decode_error') or body.get('format')=='encoded_or_binary_redacted':
            result['decode_errors'][side]=body.get('decode_error') or 'historical_decode_unconfirmed'
    observed=sample.get('field_provenance',{}).get('worker_return')
    if observed:
        result['worker_return']='write_failed_or_interrupted' if observed.get('write_failed') or observed.get('context_cancelled') or not observed.get('handler_completed') else 'written_to_broker'
    result['http_end_reason']=sample.get('http_end_reason','historical_not_recorded')
    response=sample.get('response',{});body=response.get('body',{})
    if sample.get('request',{}).get('path')!='/v1/messages':return result
    if response.get('status',0)>=400:result['model_response']='upstream_error';return result
    if body.get('format')=='json':
        value=body.get('value',{})
        if isinstance(value,dict) and value.get('type')=='message' and value.get('stop_reason') and completeness.get('response'):
            result['model_response']='complete'
        return result
    if body.get('format')!='sse':return result
    started=stopped=ended=False;invalid=False;failure=False
    event='';data=[]
    def consume():
        nonlocal started,stopped,ended,invalid,failure,event,data
        if not data:event='';return
        try:
            value=json.loads('\n'.join(data));kind=value.get('type')
            if event and event!=kind:invalid=True
            if kind=='error':failure=True
            elif kind=='message_start':
                if started or ended:invalid=True
                started=True
            elif kind=='message_delta':
                if not started or ended:invalid=True
                if value.get('delta',{}).get('stop_reason') in ('end_turn','tool_use','max_tokens','stop_sequence','pause_turn','refusal'):stopped=True
            elif kind=='message_stop':
                if not started or not stopped or ended:invalid=True
                ended=True
            elif kind in ('content_block_start','content_block_delta','content_block_stop') and (not started or ended):invalid=True
        except (ValueError,AttributeError,TypeError):invalid=True
        event='';data=[]
    for line in body.get('lines',[]):
        if not line:consume()
        elif line.startswith('event:'):event=line[6:].strip()
        elif line.startswith('data:'):data.append(line[5:].lstrip())
        elif not line.startswith(':'):invalid=True
    # An unterminated last SSE event is not evidence of successful completion.
    if data:invalid=True
    result['model_response']='upstream_error' if failure else 'complete' if ended and not invalid else 'end_unconfirmed'
    return result

def review_issues(review):
    issues=[]
    if review.get('http_request')=='end_unconfirmed':issues.append('request_capture_incomplete')
    if review.get('http_response')=='end_unconfirmed':issues.append('response_capture_incomplete')
    if review.get('worker_return')=='write_failed_or_interrupted':issues.append('worker_return_interrupted')
    if review.get('decode_errors'):issues.append('body_decode_failed')
    return issues

def capture_summary(audit,reviews,history,expected):
    """Never infer an old unscoped error belongs to the latest archive."""
    archive=audit.get('last_archive')
    belongs=lambda sample:bool(archive and sample.startswith(archive+'-'))
    current={k:v for k,v in reviews.items() if belongs(k)}
    ids=[k for k in expected if belongs(k)]
    problems=[{'sample_id':k,'codes':review_issues(v)} for k,v in current.items() if review_issues(v)]
    pending=not ids or any(k not in current for k in ids)
    complete=bool(ids) and not pending and all(current[k].get('original_full_replay_eligible') for k in ids)
    return {'archive_id':archive,'state':'issue' if problems else 'pending' if pending else 'complete' if complete else 'unconfirmed',
            'current_issues':problems,'pending_sample_ids':[k for k in ids if k not in current],
            'historical_issues':[x for x in history if not belongs(x['sample_id'])][-32:],
            'unattributed_legacy_issue':audit.get('capture_issue') or None}

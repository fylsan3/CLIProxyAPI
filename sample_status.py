"""Classify sanitized observations without changing capture/replay evidence."""
import json

def response_review(sample):
    completeness=sample.get('completeness',{})
    result={'http_response':'complete' if completeness.get('response') else 'end_unconfirmed',
            'model_response':'not_observed','client_delivery':'not_observed',
            'original_full_replay_eligible':bool(completeness.get('original_full_replay_eligible'))}
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

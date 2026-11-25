"""Bounded passive Claude usage observation. Never edits or blocks response bytes."""
import json

FIELDS=('input_tokens','output_tokens','cache_creation_input_tokens','cache_read_input_tokens')
MAX_EVENT=1024*1024

class UsageObserver:
    def __init__(self,stream):
        self.stream=stream;self.buffer=bytearray();self.event=[];self.event_size=0
        self.values={};self.invalid=False;self.terminal=False;self.started=False
    def merge(self,usage):
        if usage is None:return
        if not isinstance(usage,dict):self.invalid=True;return
        for key in FIELDS:
            if key not in usage:continue
            value=usage[key]
            if type(value) is not int or not 0<=value<=2**53-1 or value<self.values.get(key,0):self.invalid=True;continue
            # Claude stream usage counters are cumulative, not additive per event.
            self.values[key]=value
    def event_done(self):
        if not self.event:return
        raw=b'\n'.join(self.event);self.event=[];self.event_size=0
        try:
            event=json.loads(raw)
            if not isinstance(event,dict):self.invalid=True;return
            kind=event.get('type')
            if kind=='message_start':
                if self.started:self.invalid=True
                self.started=True;self.merge(event.get('message',{}).get('usage'))
            elif kind=='message_delta':self.merge(event.get('usage'))
            elif kind=='message_stop':self.terminal=True
            elif kind=='error':self.invalid=True
        except (ValueError,AttributeError,TypeError,RecursionError):self.invalid=True
    def feed(self,chunk):
        if self.invalid:return
        self.buffer.extend(chunk)
        if not self.stream:
            if len(self.buffer)>16*1024*1024:self.invalid=True;self.buffer.clear()
            return
        while b'\n' in self.buffer:
            raw,_,rest=self.buffer.partition(b'\n');self.buffer=bytearray(rest);line=bytes(raw).rstrip(b'\r')
            if not line:self.event_done()
            elif line.startswith(b'data:'):
                data=line[5:];data=data[1:] if data.startswith(b' ') else data
                self.event.append(data);self.event_size+=len(data)
            if self.event_size>MAX_EVENT:self.invalid=True;self.buffer.clear();self.event=[];return
        if len(self.buffer)>MAX_EVENT:self.invalid=True;self.buffer.clear()
    def finish(self,receipt_verified,status):
        if not self.stream and not self.invalid and self.buffer:
            try:
                value=json.loads(self.buffer)
                if isinstance(value,dict):self.merge(value.get('usage'));self.terminal=value.get('type')=='message';self.started=self.terminal
                else:self.invalid=True
            except (ValueError,TypeError,RecursionError):self.invalid=True
        state=('invalid' if self.invalid else 'unreported' if not self.values else
               'confirmed' if receipt_verified and status==200 and self.started and self.terminal and all(k in self.values for k in ('input_tokens','output_tokens')) else 'partial')
        self.buffer.clear();self.event=[]
        return {'state':state,'values':dict(self.values),'source':'provider_reported'}

def summarize(rows):
    totals={};coverage={};counts={'confirmed':0,'partial':0,'invalid':0,'unreported':0}
    for row in rows:
        value=json.loads(row['usage']) if row.get('usage') else {'state':'unreported','values':{}}
        state=value['state']
        # Receipt and usage are committed together; incomplete attempts never enter totals.
        if row['state']!='completed' and state=='confirmed':state='partial'
        counts[state]=counts.get(state,0)+1
        if state=='confirmed':
            for key,number in value['values'].items():totals[key]=totals.get(key,0)+number;coverage[key]=coverage.get(key,0)+1
    return {'totals':totals,'field_coverage':coverage,'attempt_counts':counts,'note':'provider_reported_not_billing'}

def native_usage_observation(encoded,fallback,status):
    if not encoded:return fallback
    import base64
    try:
        if len(encoded)>44000:return {'state':'invalid','values':{},'source':'native_cpa_reporter'}
        value=json.loads(base64.b64decode(encoded+'='*(-len(encoded)%4),validate=True))
        fields={'InputTokens':'input_tokens','OutputTokens':'output_tokens','CacheCreationTokens':'cache_creation_input_tokens','CacheReadTokens':'cache_read_input_tokens'}
        counts={target:value[source] for source,target in fields.items()}
        if any(type(n) is not int or not 0<=n<=2**53-1 for n in counts.values()):raise ValueError('invalid native counts')
        state='unreported' if not any(counts.values()) and fallback['state']=='unreported' else 'confirmed' if status==200 else 'partial'
        return {'state':state,'values':counts,'source':'native_cpa_reporter'}
    except (ValueError,KeyError,TypeError):return {'state':'invalid','values':{},'source':'native_cpa_reporter'}

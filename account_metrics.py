"""Read-only rolling execution statistics; never request a model or infer billing."""
import json,time
from collections import deque

def initialize(db):
    columns={r[1] for r in db.execute('PRAGMA table_info(attempts)')}
    if 'finished' not in columns:db.execute('ALTER TABLE attempts ADD COLUMN finished INTEGER')
    db.execute('CREATE INDEX IF NOT EXISTS attempts_owner_started ON attempts(owner,started)')
    db.execute('CREATE INDEX IF NOT EXISTS attempts_owner_finished ON attempts(owner,finished)')
    db.execute('CREATE TABLE IF NOT EXISTS metric_meta(key TEXT PRIMARY KEY,value INTEGER)')
    db.execute('INSERT OR IGNORE INTO metric_meta VALUES(?,?)',('completion_tracking_since',int(time.time())))

def tokens(raw):
    try:
        v=json.loads(raw or '{}');n=v.get('values',{})
        if v.get('state')!='confirmed':return None
        values=[n.get(k) for k in ('input_tokens','output_tokens')]
        if any(type(x) is not int or x<0 for x in values):return None
        return sum(values)
    except (ValueError,TypeError,AttributeError):return None

def summarize(db,owner,now=None):
    now=int(time.time()) if now is None else now
    rows=db.execute('SELECT started,state,status FROM attempts WHERE owner=? AND started>? AND started<=? ORDER BY started',(owner,now-7*86400,now)).fetchall()
    success=failed=unknown=active=peak=rpm=0;window=deque()
    for started,state,status in rows:
        while window and window[0]<=started-60:window.popleft()
        window.append(started);peak=max(peak,len(window));rpm+=started>now-60
        if state in ('preparing','running'):active+=1
        elif state=='result_unknown':unknown+=1
        elif state=='completed' and status is not None and 200<=status<300:success+=1
        elif state=='not_dispatched' or status is not None and status>=400:failed+=1
        else:unknown+=1
    recent=db.execute('SELECT state,usage FROM attempts WHERE owner=? AND finished>? AND finished<=?',(owner,now-60,now)).fetchall()
    known=[tokens(raw) for state,raw in recent if state=='completed']
    since=db.execute("SELECT value FROM metric_meta WHERE key='completion_tracking_since'").fetchone()[0]
    tpm=sum(n for n in known if n is not None) if now-since>=60 else None
    return {'observed_at':now,'last_request_at':db.execute('SELECT MAX(started) FROM attempts WHERE owner=?',(owner,)).fetchone()[0],
            'seven_day':{'success':success,'failed':failed,'unknown':unknown,'active':active,'attempts':len(rows)},
            'rpm':rpm,'peak_rpm':peak,'tpm':tpm,'tpm_incomplete':any(n is None for n in known) or any(state!='completed' for state,_ in recent),
            'completion_tracking_since':since,'scope':'account_execution_attempts_including_retries'}

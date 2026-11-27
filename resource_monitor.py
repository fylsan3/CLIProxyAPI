"""Bounded local container resource observations. No credentials or outbound HTTP."""
import concurrent.futures,json,math,re,sqlite3,subprocess,threading,time
from pathlib import Path

PROBE=r'''import json,subprocess,sys
from pathlib import Path
r=Path('/sys/fs/cgroup')
def number(name):
 try:return int((r/name).read_text().strip())
 except (OSError,ValueError):return None
v={'memory_bytes':number('memory.current'),'memory_peak_bytes':number('memory.peak'),'memory_limit_bytes':number('memory.max')}
try:v['cpu_usec']=int(dict(line.split() for line in (r/'cpu.stat').read_text().splitlines())['usage_usec'])
except (OSError,ValueError,KeyError):v['cpu_usec']=None
if sys.argv[1]=='disk':
 try:
  p=subprocess.run(['du','-sk','/state','/backup','/network-config'],capture_output=True,text=True,timeout=5)
  v['disk_bytes']=sum(int(x.split()[0])*1024 for x in p.stdout.splitlines()) if p.returncode==0 else None
 except (OSError,ValueError,subprocess.TimeoutExpired):v['disk_bytes']=None
print(json.dumps(v))
'''

def cpu_percent(previous,current):
    if not previous or previous.get('container')!=current.get('container'):return None
    a,b=previous.get('cpu_usec'),current.get('cpu_usec');dt=current['at']-previous['at']
    if a is None or b is None or b<a or dt<=0:return None
    return round((b-a)/1e6/dt*100,2)

def aggregate(samples,now):
    result={'at':now,'accounts':len(samples),'memory_bytes':None,'cpu_percent':None,'disk_bytes':None}
    for key in ('memory_bytes','cpu_percent','disk_bytes'):
        values=[s.get(key) for s in samples]
        result[key]=sum(values) if all(isinstance(x,(int,float)) and math.isfinite(x) for x in values) else None
    result['missing_accounts']=sum(bool(s.get('error')) for s in samples)
    return result

def reduce_points(rows,seconds):
    buckets={}
    for row in rows:buckets.setdefault(row['at']//seconds,[]).append(row)
    result=[]
    for bucket,points in sorted(buckets.items()):
        p={'at':max(x['at'] for x in points)}
        for key in ('memory_bytes','cpu_percent','disk_bytes'):
            values=[x.get(key) for x in points]
            p[key]=round(sum(values)/len(values),2) if all(v is not None for v in values) else None
            p[key+'_peak']=max(values) if all(v is not None for v in values) else None
        result.append(p)
    return result

class Monitor:
    def __init__(self,broker,cli):
        self.broker=broker;self.cli=cli;self.path=broker.folder/'resources.sqlite';self.lock=threading.Lock();self.latest={};self.previous={};self.disk={};self.cache=None;self.cache_at=0
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS points(at INTEGER PRIMARY KEY,data TEXT NOT NULL)')
        self.thread=threading.Thread(target=self.run,name='account-resources',daemon=True);self.thread.start()
    def connect(self):return sqlite3.connect(self.path,timeout=2)
    def command(self,args,timeout=9):
        p=subprocess.run(self.cli+args,capture_output=True,text=True,timeout=timeout)
        if p.returncode:raise ValueError('resource_probe_failed')
        return p.stdout
    def collect(self,pair):
        owner,container=pair;now=int(time.time());sample={'owner':owner,'container':container,'at':now}
        if self.broker.stopping.is_set() or not re.fullmatch('[0-9a-f]{64}',container or ''):return dict(sample,error='unavailable')
        try:
            running=self.command(['inspect','--format','{{.State.Running}}',container],3).strip()
            disk=self.disk.get(container,{})
            if running=='false':sample.update(memory_bytes=0,cpu_percent=0,disk_bytes=disk.get('disk_bytes'),disk_at=disk.get('disk_at'),stopped=True);return sample
            if running!='true':raise ValueError('unknown_state')
            scan=now-disk.get('disk_at',0)>=300
            data=json.loads(self.command(['exec','--user','1001:1001',container,'python3','-B','-c',PROBE,'disk' if scan else 'resources']))
            sample.update(data);sample['cpu_percent']=cpu_percent(self.previous.get(container),sample)
            if scan and data.get('disk_bytes') is not None:self.disk[container]={'disk_bytes':data['disk_bytes'],'disk_at':now}
            sample.update(self.disk.get(container,{}))
            if now-sample.get('disk_at',0)>600 and running=='true':sample['disk_bytes']=None
            self.previous[container]=sample.copy()
        except (OSError,ValueError,subprocess.SubprocessError,TypeError):sample['error']='resource_probe_failed'
        return sample
    def once(self):
        with self.broker.connect() as db:pairs=db.execute('SELECT owner,container FROM bindings').fetchall()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:samples=list(pool.map(self.collect,pairs))
        now=int(time.time());total=aggregate(samples,now)
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO points VALUES(?,?)',(now,json.dumps(total)))
            db.execute('DELETE FROM points WHERE at<?',(now-7*86400,))
        with self.lock:self.latest={s['owner']:s for s in samples};self.cache=None
    def run(self):
        while not self.broker.stopping.is_set():
            try:self.once()
            except (OSError,ValueError,sqlite3.Error):pass
            self.broker.stopping.wait(30)
    def snapshot(self):
        now=int(time.time())
        with self.lock:
            if self.cache is not None and now-self.cache_at<15:return self.cache
            latest={k:dict(v) for k,v in self.latest.items()}
        with self.connect() as db:rows=[json.loads(r[0]) for r in db.execute('SELECT data FROM points WHERE at>=? ORDER BY at',(now-7*86400,))]
        value={'current':rows[-1] if rows else None,'history_since':rows[0]['at'] if rows else None,'observed_at':now,'stale':not rows or now-rows[-1]['at']>90,'accounts':latest,
               'series':{'1h':[p for p in rows if p['at']>=now-3600], '24h':reduce_points([p for p in rows if p['at']>=now-86400],300),'7d':reduce_points(rows,3600)},
               'scope':'account_volumes_only','sample_seconds':30,'disk_seconds':300}
        with self.lock:self.cache=value;self.cache_at=now
        return value

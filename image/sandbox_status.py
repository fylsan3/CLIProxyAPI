"""Read-only evidence for Chromium's renderer sandbox, without recording URLs."""
import os,time
from pathlib import Path

def status(pid):
    return dict(line.split(':',1) for line in (Path('/proc')/str(pid)/'status').read_text().splitlines() if ':' in line)

def inspect(browser_pid):
    parent=status(browser_pid);baseline=int(parent.get('Seccomp_filters','0'))
    browser_args=(Path('/proc')/str(browser_pid)/'cmdline').read_bytes().replace(b'\0',b' ').split()
    disabled=any(flag in browser_args for flag in (b'--no-sandbox',b'--disable-seccomp-filter-sandbox',b'--disable-namespace-sandbox'))
    rows=[]
    for entry in Path('/proc').glob('[0-9]*'):
        try:
            args=(entry/'cmdline').read_bytes().replace(b'\0',b' ').split()
            if b'--type=renderer' not in args:continue
            value=status(entry.name)
            rows.append({'uid':int(value['Uid'].split()[0]),'effective_capabilities':int(value['CapEff'].strip(),16),
                         'seccomp_mode':int(value['Seccomp']),'filters':int(value.get('Seccomp_filters','0')),
                         'pid_namespace_depth':len(value.get('NSpid','').split()),'no_new_privileges':value['NoNewPrivs'].strip()=='1'})
        except (OSError,ValueError,KeyError):continue
    ready=bool(rows) and not disabled and all(r['uid']==os.getuid() and r['effective_capabilities']==0 and r['seccomp_mode']==2 and
                    r['filters']>baseline and r['pid_namespace_depth']>len(parent.get('NSpid','').split()) and r['no_new_privileges'] for r in rows)
    return {'verified':ready,'disabled_by_flag':disabled,'browser_filter_count':baseline,'renderers':rows}

def wait_for_sandbox(process):
    deadline=time.monotonic()+8
    while time.monotonic()<deadline:
        if process.poll() is not None:break
        try:
            result=inspect(process.pid)
            if result['verified']:return result
        except (OSError,ValueError):pass
        time.sleep(.1)
    raise ValueError('browser_sandbox_unavailable')

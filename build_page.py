"""Pin the native asset and embed the account view using its login and theme stores."""
import hashlib,json,re
from pathlib import Path
r=Path(__file__).resolve().parent
source=(Path.home()/'cliproxyapi/static/management.html').read_bytes()
if hashlib.sha256(source).hexdigest()!='13674049eb63ef2d3df8daf58aa1f42b397460ab5fedebd43a3bfc48fe20bbc7' or source.count(b'</script>')!=1:
    raise SystemExit('Management asset changed; review its session/theme adapter before building.')
css=(r/'ui/style.css').read_text().split('\n',2)[2]
css=css.replace('body{margin:0}', ':host{display:block;font:15px/1.55 system-ui,sans-serif;color:var(--text-primary);background:var(--bg-primary)}[hidden]{display:none!important}*{box-sizing:border-box}')
css=css.replace('background:var(--primary-active);color:var(--primary-contrast)', 'background:var(--text-primary);color:var(--bg-primary)').replace('button:active{background:var(--primary-active)}','button:active{background:var(--text-primary)}')
css+='''
nav{display:flex;align-items:center;gap:12px;flex-wrap:wrap;max-width:1100px;margin:auto;padding:14px 24px;border-bottom:1px solid var(--border-color)}nav a{display:inline-flex;align-items:center;min-height:44px;padding:8px;text-decoration:none}nav a[aria-current]{font-weight:700;text-decoration:underline}.nav-spacer{flex:1}nav button{background:var(--bg-secondary);color:var(--text-primary)}nav button:hover{background:var(--bg-tertiary)}article button{margin:6px 8px 6px 0}main>p{max-width:75ch}.good{color:var(--success-badge-text);background:var(--success-badge-bg);padding:4px 8px;border-radius:4px;width:fit-content}::selection{background:var(--primary-active);color:var(--primary-contrast)}input{caret-color:var(--text-primary)}:host{scrollbar-color:var(--border-primary) var(--bg-primary);font-variant-numeric:tabular-nums}@media(max-width:600px){nav{padding:10px 16px;gap:8px}.nav-spacer{display:none}nav button{flex:1 1 calc(50% - 4px);white-space:nowrap}}
'''
markup=(r/'ui/index.html').read_text();markup=markup[markup.index('<main>'):markup.index('</main>')+7]
markup=re.sub(r'<p class="eyebrow">.*?</p>','',markup)
app=(r/'ui/app.js').read_text()
app=re.sub(r"if\(location.hash.length>1\)\{.*?\}\n",'',app,count=1)
app=app.replace('请使用测试启动目录中 status-page.json 的完整地址打开。','请返回管理首页登录。').replace('查看凭证失效，请重新打开测试地址。','管理登录失效，请重新登录。')
script=(r/'ui/integration.js').read_text()
for key,value in {'CSS':css.replace('\\','\\\\').replace("'","\\'").replace('\n',''), 'MARKUP':json.dumps(markup,ensure_ascii=False),'QUOTA':(r/'ui/quota_view.js').read_text(),'SETTINGS':(r/'ui/settings.js').read_text(),'APP':app}.items():
    script=script.replace('__'+key+'__',value)
assert '</script>' not in script
(r/'static/management.local.html').write_bytes(source.replace(b'</script>',b'\n'+script.encode()+b'\n</script>',1))
(r/'static/management.html').write_bytes(source)
(r/'ui/compiled.js').write_text(script)
print('Management asset built with native login and theme bindings')

"""Pin the native asset and embed the account view using its login and theme stores."""
import hashlib,json,re
from pathlib import Path
r=Path(__file__).resolve().parent
source=(r/'static/management.html').read_bytes()
if hashlib.sha256(source).hexdigest()!='13674049eb63ef2d3df8daf58aa1f42b397460ab5fedebd43a3bfc48fe20bbc7' or source.count(b'</script>')!=1:
    raise SystemExit('Management asset changed; review its session/theme adapter before building.')
css=(r/'ui/style.css').read_text()
markup=(r/'ui/index.html').read_text();markup=markup[markup.index('<main>'):markup.index('</main>')+7]
markup=re.sub(r'<p class="eyebrow">.*?</p>','',markup)
app=(r/'ui/app.js').read_text()
app=re.sub(r"if\(location.hash.length>1\)\{.*?\}\n",'',app,count=1)
app=app.replace('请使用测试启动目录中 status-page.json 的完整地址打开。','请返回管理首页登录。').replace('查看凭证失效，请重新打开测试地址。','管理登录失效，请重新登录。')
script=(r/'ui/integration.js').read_text()
for key,value in {'CSS':css.replace('\\','\\\\').replace("'","\\'").replace('\n',''), 'MARKUP':json.dumps(markup,ensure_ascii=False),'QUOTA':(r/'ui/quota_view.js').read_text(),'SETTINGS':(r/'ui/settings.js').read_text(),'PROGRESS':(r/'ui/creation.js').read_text(),'NAVIGATION':(r/'ui/navigation.js').read_text(),'APP':app}.items():
    script=script.replace('__'+key+'__',value)
assert '</script>' not in script
(r/'static/management.local.html').write_bytes(source.replace(b'</script>',b'\n'+script.encode()+b'\n</script>',1))
(r/'static/management.html').write_bytes(source)
(r/'ui/compiled.js').write_text(script)
print('Management asset built with native login and theme bindings')

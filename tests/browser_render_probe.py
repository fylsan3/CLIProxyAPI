import glob,subprocess,json,sys,os,time,threading,http.server,pathlib
sys.path.insert(0,'/opt/sample')
from desktop import Desktop
html='''<title>Local rendering acceptance</title><script>
(async()=>{let steps=[]; async function mark(s){steps.push(s); await fetch('/result?'+encodeURIComponent(s));}
await mark('html'); new WebAssembly.Module(new Uint8Array([0,97,115,109,1,0,0,0]));await mark('wasm');
window.canvases=[];for(let i=0;i<6;i++){let c=document.createElement('canvas'); c.width=4096;c.height=4096;let ctx=c.getContext('2d');ctx.fillRect(0,0,4096,4096);window.canvases.push(await createImageBitmap(c));}await mark('canvas');
let db=await new Promise((ok,no)=>{let r=indexedDB.open('local-test',1);r.onupgradeneeded=()=>r.result.createObjectStore('items');r.onsuccess=()=>ok(r.result);r.onerror=()=>no(r.error)});await mark('indexeddb');
let cache=await caches.open('local-test');await cache.put('/stored',new Response('sample'));await mark('cache');
await navigator.storage.getDirectory();await mark('opfs');await mark('done');
})().catch(e=>fetch('/result?error='+encodeURIComponent(e.name+':'+e.message)));
</script>'''.encode()
results=[];done=threading.Event()
class H(http.server.BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_GET(self):
  self.send_response(200);self.end_headers()
  if self.path.startswith('/result?'):
   s=self.path.split('?',1)[1];results.append(s)
   if s=='html':
    with pathlib.Path('/tmp/pressure').open('wb') as f:
     for _ in range(180):
      try:f.write(b'x'*(1024*1024))
      except OSError:break
   if s=='done' or s.startswith('error='):done.set()
  else:self.wfile.write(html)
server=http.server.ThreadingHTTPServer(('127.0.0.1',8766),H);threading.Thread(target=server.serve_forever,daemon=True).start()
d=Desktop();d.start();chrome=glob.glob('/ms-playwright/chromium-*/**/chrome',recursive=True)[0]
err=pathlib.Path('/tmp/chrome.log').open('w+')
p=subprocess.Popen([chrome,'--ozone-platform=x11','--lang=en-US','--disable-dev-shm-usage','--disable-background-networking','--no-first-run','--user-data-dir=/tmp/test-browser','http://127.0.0.1:8766'],env=d.env,stdout=subprocess.DEVNULL,stderr=err)
done.wait(12);p.terminate();p.wait(5);d.close();server.shutdown();err.seek(0);log=err.read()
print(json.dumps({'steps':results,'done':'done' in results,'diagnostic':[x for x in log.splitlines() if any(t in x.lower() for t in ['fatal','signal','trap','memory','denied','check failed'])]}))

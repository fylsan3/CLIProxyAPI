// Fictional local data only; checks range selection and missing observations.
const assert=require('node:assert/strict');
const {chromium}=require(process.env.CPA_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const origin='http://127.0.0.1:18322';let state='normal';const errors=[],writes=[];
 const b=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
 try{
  const p=await b.newPage({viewport:{width:1280,height:1000}});
  p.on('pageerror',e=>errors.push(e.message));p.on('request',r=>{if(r.method()==='POST')writes.push(r.url());});
  await p.route('**/*',async route=>{
   if(new URL(route.request().url()).origin!==origin)return route.abort();
   if(route.request().url().endsWith('/account-environments/snapshot')){
    const response=await route.fetch(),data=await response.json();
    if(state==='stale')data.resource_monitor.stale=true;
    if(state==='missing'){data.resource_monitor.current.disk_bytes=null;for(const rows of Object.values(data.resource_monitor.series))for(const row of rows)row.disk_bytes=null;}
    return route.fulfill({response,json:data});
   }
   return route.continue();
  });
  await p.goto(origin+'/accounts.html');
  if(await p.getByPlaceholder('请输入管理密钥').isVisible()){await p.getByPlaceholder('请输入管理密钥').fill('fictional-only');await p.getByRole('button',{name:'登录',exact:true}).click();}
  const monitor=p.locator('#resource-monitor'),overview=p.locator('.overview'),toggle=monitor.locator('.monitor-toggle');await toggle.waitFor();await p.locator('.main-content #account-environments-app').waitFor();
  await p.locator('#count-all').click();assert.equal(await toggle.getAttribute('aria-expanded'),'true');
  await p.locator('#count-ready').click();assert.equal(await toggle.getAttribute('aria-expanded'),'false');
  await overview.click({position:{x:(await overview.boundingBox()).width-5,y:5}});assert.equal(await toggle.getAttribute('aria-expanded'),'true');
  await monitor.locator('.monitor-help').click();assert.equal(await toggle.getAttribute('aria-expanded'),'true');
  await toggle.click();
  assert.equal(await toggle.getAttribute('aria-expanded'),'false');assert((await overview.boundingBox()).height<=70);
  await p.screenshot({path:'/tmp/cpa-ui21-collapsed.png'});await toggle.click();await monitor.locator('.resource-chart path').first().waitFor();
  await p.screenshot({path:'/tmp/cpa-ui21-expanded.png'});
  assert.equal(await monitor.locator('.resource-chart').count(),3);
  for(const name of ['近 24 小时','近 7 天','近 1 小时']){const button=monitor.getByRole('button',{name,exact:true});await button.click();assert.equal(await button.getAttribute('aria-pressed'),'true');assert.equal(await toggle.getAttribute('aria-expanded'),'true');}
  const svg=monitor.locator('svg').first();await svg.focus();await p.keyboard.press('ArrowLeft');assert((await monitor.locator('.chart-caption').first().innerText()).includes(' · '));
  assert((await p.locator('.account-card').first().boundingBox()).width<=320);
  // Missing current observations must not be displayed as zero.
  assert.equal(await toggle.getAttribute('aria-expanded'),'true');state='missing';await p.waitForTimeout(6000);assert.equal(await monitor.locator('.resource-chart').nth(2).locator('figcaption strong').innerText(),'未统计');
  state='stale';await p.waitForTimeout(6000);assert.equal(await monitor.locator('figcaption strong').first().innerText(),'未统计');
  await toggle.click();await p.waitForTimeout(5500);assert.equal(await toggle.getAttribute('aria-expanded'),'false');
  await p.setViewportSize({width:390,height:844});await overview.scrollIntoViewIfNeeded();await p.screenshot({path:'/tmp/cpa-ui21-mobile.png'});assert((await overview.boundingBox()).height<=150);assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
  console.log(JSON.stringify({passed:true,ranges:3,keyboard:true,missing_and_stale:true,width:320,mobile:true,account_calls:0}));
 }finally{await b.close();}
})().catch(e=>{console.error(e);process.exit(1)});

// Fictional loopback preview only. Does not call production management or accounts.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(process.env.CPA_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const url=process.env.CPA_UI_PREVIEW_URL||'http://127.0.0.1:18320',output=process.env.CPA_UI_OUTPUT||'/tmp/cpa-ui18';
 assert.equal(new URL(url).hostname,'127.0.0.1');fs.mkdirSync(output,{recursive:true});
 const b=await chromium.launch({executablePath:process.env.CPA_TEST_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
 try{
  const p=await b.newPage({viewport:{width:1280,height:900}}),errors=[],writes=[];
  p.on('pageerror',e=>errors.push(e.message));p.on('request',r=>{if(r.method()==='POST'&&!r.url().endsWith('/preview-mode'))writes.push(r.url());});
  await p.route('**/*',route=>new URL(route.request().url()).origin===url?route.continue():route.abort());
  async function mode(value){assert((await p.request.post(url+'/preview-mode',{data:{mode:value}})).ok());await p.goto(url+'/accounts.html');if(await p.getByPlaceholder('请输入管理密钥').isVisible()){await p.getByPlaceholder('请输入管理密钥').fill('fictional-preview-only');await p.getByRole('button',{name:'登录',exact:true}).click();}await p.locator('.account-card').first().waitFor();await p.locator('.main-content #account-environments-app').waitFor();await p.waitForTimeout(300);}
  const a=p.locator('.account-card[data-account="research-a"]'),other=p.locator('.account-card[data-account="research-b"]');
  await mode('populated');assert((await a.boundingBox()).width<=340);await p.screenshot({path:path.join(output,'cards.png')});
  await a.getByRole('button',{name:/详情/}).click();await a.getByRole('tab',{name:'用量',exact:true}).click();await p.waitForTimeout(5400);assert.equal(await a.getByRole('tab',{name:'用量',exact:true}).getAttribute('aria-selected'),'true');
  await a.getByRole('tab',{name:'备份',exact:true}).click();assert(await a.getByRole('button',{name:'更新加密备份',exact:true}).isVisible());
  await a.getByRole('tab',{name:'概览',exact:true}).click();await p.screenshot({path:path.join(output,'details.png')});
  await p.keyboard.press('End');assert.equal(await a.getByRole('tab',{name:'记录',exact:true}).getAttribute('aria-selected'),'true');
  await p.keyboard.press('Escape');await p.waitForTimeout(350);assert.equal(await p.locator('.detail-portal').count(),0);
  for(const state of ['f5-empty','f5-zero','f5-inactive']){
   await mode(state);assert.equal(await a.locator('.card-main').getByText('Fable 5 · 7 天',{exact:true}).count(),state==='f5-zero'?1:0);
   if(state==='f5-zero')assert((await a.locator('.card-main').innerText()).includes('剩余 100%'));
   if(state==='f5-inactive'){await a.getByRole('button',{name:/详情/}).click();await a.getByRole('tab',{name:'用量',exact:true}).click();assert(await a.getByText('未启用',{exact:true}).isVisible());}
  }
  await mode('status-colors');assert((await other.getAttribute('class')).includes('has-issue'));assert(!(await a.getAttribute('class')).includes('has-issue'));
  const beam=other.locator('.border-beam');assert(await beam.isVisible());const offset=()=>beam.evaluate(e=>getComputedStyle(e,'::before').offsetDistance);const first=await offset();await p.waitForTimeout(600);assert.notEqual(await offset(),first);await p.screenshot({path:path.join(output,'abnormal.png')});
  await p.setViewportSize({width:390,height:844});await mode('populated');await a.getByRole('button',{name:/详情/}).click();await a.getByRole('tab',{name:'用量',exact:true}).click();await p.waitForTimeout(400);
  assert(await p.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));assert(await a.evaluate(e=>e.scrollWidth<=e.clientWidth+1));await p.screenshot({path:path.join(output,'mobile-details.png')});
  await p.emulateMedia({reducedMotion:'reduce'});await mode('status-colors');assert.equal(await beam.evaluate(e=>getComputedStyle(e,'::before').animationName),'none');
  assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);
  console.log(JSON.stringify({passed:true,width:340,f5_cases:3,details_poll_and_keyboard:true,red_beam_animated:true,mobile_no_overflow:true,reduced_motion:true,account_actions:0,screenshots:output}));
 }finally{await b.close();}
})().catch(e=>{console.error(e);process.exit(1)});

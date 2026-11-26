// Launched only with an ephemeral fixture URL and fictional management key via stdin.
const fs=require('fs'),assert=require('assert');
const {chromium}=require(process.env.CPA_PLAYWRIGHT_MODULE||'playwright');
(async()=>{
 const input=JSON.parse(fs.readFileSync(0,'utf8'));assert(input.url.startsWith('http://127.0.0.1:'));
 const browser=await chromium.launch({executablePath:process.env.CPA_TEST_CHROME||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true});
 try{
  const p=await browser.newPage();const errors=[],actions=[];p.on('pageerror',e=>errors.push(e.message));
  p.on('request',r=>{if(r.method()==='POST'&&r.url().endsWith('/account-environments/action'))actions.push(r.postDataJSON());});
  await p.goto(input.url);await p.getByPlaceholder('请输入管理密钥').fill(input.key);await p.getByRole('button',{name:'登录',exact:true}).click();
  const card=p.locator('[data-account="a"]');await card.waitFor();const refresh=card.getByRole('button',{name:'刷新用量',exact:true});
  await refresh.click();await p.getByRole('button',{name:'取消',exact:true}).click();assert.equal(actions.length,0);
  await refresh.click();await p.keyboard.press('Escape');assert.equal(actions.length,0);
  await refresh.click();await p.waitForTimeout(5200); // state poll must not dismiss or submit the confirmation
  assert(await p.getByRole('dialog',{name:'确定刷新用量？'}).isVisible());assert.equal(actions.length,0);
  const response=p.waitForResponse(r=>r.request().method()==='POST'&&r.url().endsWith('/account-environments/action'));
  await p.getByRole('button',{name:'确定刷新',exact:true}).click();const res=await response;assert.equal(res.status(),200);
  const value=await res.json();assert.equal(value.ok,!input.partial);assert.equal(!!value.partial,!!input.partial);assert(value.operation_id);
  assert.deepEqual(actions,[{slug:'a',action:'account-update'}]);await p.waitForFunction(()=>document.querySelector('#account-environments-app').shadowRoot.querySelector('#progress').textContent.includes('操作记录：'));
  await card.locator('.detail-toggle').click();await p.getByText('中央管理已收到确认请求',{exact:false}).waitFor();
  assert((await card.locator('.detail-content').innerText()).includes(value.operation_id));assert.deepEqual(errors,[]);
  console.log(JSON.stringify({passed:true,cancel_and_escape_sent_no_request:true,poll_preserved_confirmation:true,confirmed_actions:actions.length,partial:!!input.partial,operation_id:value.operation_id,archive_id:value.account_observation.capture.id}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exit(1)});

const fs=require('fs'),assert=require('assert');
const {chromium}=require(process.env.CPA_PLAYWRIGHT_MODULE);
(async()=>{
 const cfg=JSON.parse(fs.readFileSync(0,'utf8'));assert(cfg.url.startsWith('http://127.0.0.1:'));
 const browser=await chromium.launch({executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless:true,args:['--disable-background-networking']});
 try{
  const page=await browser.newPage({viewport:{width:1280,height:900}});const errors=[];
  await page.route('**/*',route=>route.request().url().startsWith('http://127.0.0.1:')?route.continue():route.abort());
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(cfg.url);await page.getByPlaceholder('请输入管理密钥').fill(cfg.key);await page.getByRole('button',{name:'登录',exact:true}).click();
  await page.getByRole('link',{name:'账号管理',exact:false}).first().click();
  const card=page.locator('[data-account="a"]');await card.waitFor();
  await card.getByRole('button',{name:'Claude Code',exact:true}).click();
  const dialog=page.locator('.claude-terminal-dialog');await dialog.waitFor({state:'visible'});
  await dialog.getByText('未运行 · 仅在 API 调用或手动启动时运行',{exact:true}).waitFor();
  await dialog.getByRole('button',{name:'启动 Claude Code',exact:true}).click();
  await dialog.getByText('Claude Code 2.1.331 · 可直接输入和操作',{exact:true}).waitFor();
  await dialog.locator('.xterm-helper-textarea').focus();await page.keyboard.press('Enter');
  await page.waitForTimeout(1000);
  await page.screenshot({path:process.env.CPA_CLAUDE_SCREENSHOT||'/tmp/cpa-claude-terminal.png'});
  await dialog.getByRole('button',{name:'收起',exact:true}).click();
  await card.getByRole('button',{name:'Claude Code',exact:true}).click();assert(await dialog.isVisible());
  await dialog.getByText('终端运行中 · 收起窗口后仍运行',{exact:true}).waitFor();
  await dialog.getByRole('button',{name:'关闭终端',exact:true}).click();await dialog.getByText('终端已关闭，API 可以接收新任务；账号没有登出。',{exact:true}).waitFor();
  await dialog.getByRole('button',{name:'收起',exact:true}).click();
  await page.locator('[data-account="b"]').getByRole('button',{name:'Claude Code',exact:true}).click();
  await page.getByRole('heading',{name:'Claude Code · Fictional B',exact:true}).waitFor();
  await page.getByText('未运行 · 仅在 API 调用或手动启动时运行',{exact:true}).waitFor();
  assert.deepEqual(errors,[]);console.log(JSON.stringify({passed:true,terminal_open_input_hide_reopen_close:true,account_switch_isolated:true,page_errors:errors}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});

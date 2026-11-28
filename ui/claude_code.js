let claudeWindow=null;
async function claudeAction(slug,op,values={}){
 const response=await fetch('/action',{method:'POST',headers:{'Content-Type':'application/json','X-Offline-View':sessionStorage.getItem(tokenKey)},body:JSON.stringify({action:'claude-'+op,slug,...values})});
 const data=await response.json();
 if(!response.ok||data.error)throw Error(({claude_code_not_installed_or_unavailable:'这个容器尚未安装 Claude Code 测试镜像。',claude_busy_close_terminal_first:'请先关闭交互终端，再发送 API 消息。关闭终端不会退出账号。',claude_busy:'当前有 API 任务，请等待完成。',account_proxy_unavailable:'账号网络不可用，请检查 SOCKS。'})[data.error]||data.error||'操作未完成');
 return data;
}
async function openClaudeTerminal(project){
 if(claudeWindow?.slug===project.slug){claudeWindow.dialog.showModal();return;}
 if(claudeWindow){claudeWindow.cleanup();claudeWindow.dialog.remove();}
 const dialog=document.createElement('dialog');dialog.className='claude-terminal-dialog';
 document.querySelector('main')?.append(dialog);
 if(!dialog.isConnected)accounts.parentElement.append(dialog);
 const heading=text(dialog,'div','','claude-terminal-heading');text(heading,'h2','Claude Code · '+(project.label||project.slug));
 const close=text(heading,'button','收起','secondary');close.onclick=()=>dialog.close();
 const lifecycle=text(dialog,'p','正在读取运行状态…','help');
 const notice=text(dialog,'p','正在连接容器…','help');
 const tools=text(dialog,'div','','claude-terminal-actions');
 const launch=text(tools,'button','启动 Claude Code');const auth=text(tools,'button','认证状态','secondary');
 const browser=text(tools,'button','容器浏览器','secondary');const stop=text(tools,'button','关闭终端','secondary');
 const host=text(dialog,'div','','claude-terminal-host');
 const note=text(dialog,'p','与 Go 共用该账号授权，只有 Go 刷新凭据。请在账号卡片完成原有授权，不要在 CLI 中另行 /login。收起仅隐藏窗口；使用独立 API 前请关闭终端。','help');
 text(dialog,'p','API：POST /v1/claude-code/messages · account：'+project.slug,'help');
 const term=new window.Terminal({cols:100,rows:27,fontSize:13,convertEol:false,scrollback:3000,theme:{background:'#111827',foreground:'#e5e7eb'}});
 dialog.showModal();term.open(host);
 let id=null,offset=0,reading=false,closed=false,checking=false,input=Promise.resolve();
 const showState=value=>{lifecycle.textContent=({idle:'未运行 · 仅在 API 调用或手动启动时运行',starting:'启动中',running:value.mode==='terminal'?'终端运行中 · 收起窗口后仍运行':'API 任务运行中',cleaning:'清理中 · 完成后自动释放任务位置'})[value.state]||'正在读取运行状态';launch.disabled=value.busy||value.state==='cleaning';stop.disabled=!value.terminal_running;};
 const checkState=async()=>{if(closed||checking)return;checking=true;try{showState(await claudeAction(project.slug,'status'));}catch(e){lifecycle.textContent='状态暂不可用';}finally{checking=false;}};
 const say=e=>{notice.textContent=e.message||String(e);notice.className='status-bad';};
 const read=async()=>{
  if(!id||reading||closed)return;reading=true;
  try{const value=await claudeAction(project.slug,'terminal-read',{id,offset});offset=value.offset;if(value.data){const raw=atob(value.data);term.write(Uint8Array.from(raw,x=>x.charCodeAt(0)));}if(value.exit_code!==null){notice.textContent='终端进程已结束。Go 授权和环境仍保留。';id=null;await checkState();}}
  catch(e){say(e);}finally{reading=false;}
 };
 async function start(mode){
  try{notice.textContent=mode==='login'?'正在启动官方登录流程…':'正在启动 Claude Code…';const value=await claudeAction(project.slug,'terminal-start',{mode,cols:100,rows:27});id=value.id;offset=0;term.reset();notice.textContent='Claude Code 2.1.331 · 可直接输入和操作';notice.className='help';await read();await checkState();term.focus();}
  catch(e){say(e);}
 }
 term.onData(data=>{if(!id)return;const session=id,bytes=new TextEncoder().encode(data);for(let start=0;start<bytes.length;start+=2048){let raw='';for(const v of bytes.subarray(start,start+2048))raw+=String.fromCharCode(v);input=input.then(()=>claudeAction(project.slug,'terminal-input',{id:session,data:btoa(raw)})).catch(say);}});
 launch.onclick=()=>start('interactive');
 function authText(value){const a=value.authentication||{};return a.ready?'共用 Go 授权 · 凭据修订 '+a.revision+' · 刷新由 Go 负责':'Go 授权暂不可用：'+(({ go_authorization_required:'请先在账号卡片完成授权',waiting_for_go_refresh:'访问令牌已过期，等待 Go 更新',separate_claude_login_present:'发现单独的 CLI 登录记录，请先处理授权冲突',go_account_disabled:'账号已停用'})[a.error]||a.error||'请检查账号状态');}
 auth.onclick=async()=>{try{notice.textContent=authText(await claudeAction(project.slug,'status'));}catch(e){say(e);}};
 browser.onclick=async()=>{const tab=window.open('about:blank','_blank');try{const data=await claudeAction(project.slug,'browser-open');if(tab){tab.opener=null;tab.location.href=data.viewer_url;}else say('请允许弹出窗口后重新打开容器浏览器。');}catch(e){tab?.close();say(e);}};
 stop.onclick=async()=>{try{if(id)await claudeAction(project.slug,'terminal-stop',{id});await read();id=null;await checkState();notice.textContent='终端已关闭，API 可以接收新任务；账号没有登出。';}catch(e){say(e);}};
 const timer=setInterval(read,600),statusTimer=setInterval(checkState,2000);
 claudeWindow={slug:project.slug,dialog,cleanup:()=>{closed=true;clearInterval(timer);clearInterval(statusTimer);term.dispose();}};
 try{const value=await claudeAction(project.slug,'status');showState(value);notice.textContent=value.version+' · '+authText(value);if(value.terminal_id){id=value.terminal_id;await read();}}
 catch(e){say(e);}
}

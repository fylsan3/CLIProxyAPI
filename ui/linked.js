// All container management views share the account snapshot. No provider credentials are copied.
(()=>{
 const names={'/':'仪表盘','/quota':'配额管理','/system':'模型信息'};
 const contextual={'/logs':'容器请求与回执','/config':'容器配置同步','/recommended-config':'容器运行配置','/ai-providers':'Claude 订阅账号'};
 const box=nativeDocument.createElement('div');box.id='container-management-linked';box.hidden=true;const view=box.attachShadow({mode:'open'});
 const css=nativeDocument.createElement('style');css.textContent='html[data-container-page] .main-content > :not(#container-management-linked){position:absolute!important;top:0;left:0;width:100%;visibility:hidden!important;pointer-events:none!important}html[data-container-page] .main-content > :not(#container-management-linked) *{visibility:hidden!important;pointer-events:none!important}#container-management-linked{min-width:0}#container-management-linked[hidden]{display:none!important}';nativeDocument.head.append(css);
 let last='',abort=null,timer=null,known=false,busy=false,requestAccount='';
 const route=()=>location.hash.replace(/^#/,'').split('?')[0]||'/';
 const el=(parent,tag,value,cls)=>{const e=nativeDocument.createElement(tag);if(value!==undefined)e.textContent=String(value);if(cls)e.className=cls;parent.append(e);return e;};
 const text=el;
 __QUOTA__
 function link(parent,label,slug){const a=el(parent,'a',label,'button-link secondary');a.href='/accounts.html'+(slug?'?account='+encodeURIComponent(slug):'')+'#/';a.onclick=e=>{if(e.button||e.metaKey||e.ctrlKey||e.shiftKey)return;e.preventDefault();navigate(a.href);};return a;}
 function status(p){if(p.overall_ready)return '可接单';if(p.container_ready&&p.central_dispatch?.eligible!==true)return ({cooldown:'调度冷却中',disabled:'调度已停用',unavailable:'调度暂不可用',unknown:'调度状态未知'})[p.central_dispatch?.reason]||'调度暂不可用';return ({account_maintenance:'重启检查中',account_proxy_unavailable:'账号代理或出口检查失败',proxy_unavailable:'代理不可用',proxy_check_failed:'代理检查失败',container_stopped:'容器已停止',worker_unavailable:'执行器不可用',network_status_unknown:'网络状态未知',binding_check_failed:'环境绑定检查失败'})[p.reason]||(p.state?.authorized?'暂不可接单':'需要处理授权');}
 function section(parent,title){const s=el(parent,'section',undefined,'linked-section');el(s,'h2',title);return s;}
 function table(parent,headers,rows){const wrap=el(parent,'div',undefined,'linked-table-wrap'),t=el(wrap,'table'),head=el(t,'thead'),tr=el(head,'tr');headers.forEach(h=>el(tr,'th',h));const body=el(t,'tbody');for(const row of rows){const tr=el(body,'tr');row.forEach(v=>{const td=el(tr,'td');if(typeof v==='function')v(td);else td.textContent=v??'未报告';});}if(!rows.length)el(parent,'p','暂无记录。','help');}
 function render(data,path){
  updateContainerNavigation(data);
  const openDetails=new Set([...view.querySelectorAll('details[open][data-detail-key]')].map(e=>e.dataset.detailKey));
  const expanded=view.querySelector('details')?.open,focused=view.activeElement?.getAttribute('data-focus-key');
  view.replaceChildren();const style=el(view,'style');style.textContent=`:host{display:block;color:var(--text-primary,#222);font:14px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}:host([hidden]){display:none!important}*{box-sizing:border-box}main{max-width:1200px;margin:0 auto;padding:10px 0 28px}h1{font-size:28px;margin:0 0 8px}h2{font-size:18px;margin:0 0 12px}p{margin:8px 0;max-width:75ch}.help{color:var(--text-secondary,#555)}.linked-section{margin-top:28px}.linked-summary{display:flex;flex-wrap:wrap;gap:12px 28px;padding:18px 0;border-bottom:1px solid var(--border-color,#ddd)}.linked-summary strong{font-size:24px;font-variant-numeric:tabular-nums;margin-left:10px}.linked-table-wrap{max-width:100%;overflow:auto}table{border-collapse:collapse;width:100%;text-align:left}th,td{padding:12px 14px;border-bottom:1px solid var(--border-color,#ddd);vertical-align:top;overflow-wrap:anywhere;max-width:420px}th{font-weight:600;color:var(--text-secondary,#555)}a,button{color:var(--text-primary,#222);border:1px solid var(--border-color,#bbb);border-radius:8px;padding:9px 13px;display:inline-block;background:var(--bg-secondary,#fff);text-decoration:none;font:inherit;cursor:pointer}a:hover,button:hover{background:var(--bg-tertiary,#eee)}a:focus-visible,button:focus-visible,summary:focus-visible,select:focus-visible{outline:2px solid var(--text-primary,#222);outline-offset:3px}.ok{color:var(--success-color,#177044)}.bad,.status-bad{color:var(--error-color,#b42318)}.linked-actions{display:flex;gap:10px;flex-wrap:wrap;margin:16px 0}.linked-notice{padding:14px 0;border-bottom:1px solid var(--border-color,#ddd)}details{border-top:1px solid var(--border-color,#ddd);margin:24px 0;padding-top:16px}summary{cursor:pointer;font-weight:600}.account-quota{display:grid;gap:16px;max-width:560px;margin:16px 0}.quota-heading{display:flex;justify-content:space-between;gap:12px}.quota-heading strong{white-space:nowrap}.quota-countdown{font-size:12px;color:var(--text-secondary,#555)}.quota-meter{height:6px;border-radius:3px;background:var(--bg-tertiary,#ddd);overflow:hidden;margin-top:8px}.quota-meter span{display:block;height:100%;background:var(--success-color,#177044)}.quota-stale .quota-meter span{background:var(--text-secondary,#777)}.quota-warning .quota-meter span{background:#b77912}.quota-danger .quota-meter span{background:var(--error-color,#b42318)}.quota-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,340px),460px));gap:20px;margin-top:24px}.quota-card{border:1px solid var(--border-color,#ddd);border-radius:16px;padding:20px;background:var(--bg-secondary,#fff);min-width:0}.quota-card h2{overflow-wrap:anywhere}.quota-card details{margin:20px 0}.quota-card a{padding:5px 10px;font-size:12px}.quota-card p{overflow-wrap:anywhere}@media(max-width:600px){h1{font-size:24px}th,td{padding:10px 8px;min-width:85px}.linked-summary{gap:10px 18px}}`;
  const shell=el(view,names[path]?'main':'details'),main=names[path]?shell:el(shell,'div'),projects=data.projects||[],summary=data.summary||{},config=data.scheduler_config||{};
  if(names[path])el(main,'h1',names[path]);else{shell.open=!!expanded;const caption=nativeDocument.createElement('summary');caption.textContent=contextual[path];caption.dataset.focusKey='context';shell.prepend(caption);}
  el(main,'p','账号独立容器 · 与「账号管理」使用同一份状态','help');
  const actions=el(main,'div',undefined,'linked-actions');link(actions,'管理账号与容器');const reload=el(actions,'button',path==='/quota'?'更新本地显示':'刷新状态');reload.dataset.focusKey='refresh';reload.onclick=()=>poll(path);
  const stats=el(main,'div',undefined,'linked-summary');for(const [name,value] of [['账号',projects.length],['可接单',projects.filter(p=>p.overall_ready).length],['在途请求',data.scheduler_in_flight??'未知']]){const item=el(stats,'span',name);el(item,'strong',value);}
  if(data.central_status_available===false)el(main,'p','中央调度状态暂时无法确认；当前不显示旧配置，也不把未知的在途请求当作零。','bad');
  const accountRows=()=>projects.map(p=>[p.label||p.slug,p.slug,td=>el(td,'span',status(p),p.overall_ready?'ok':'bad'),p.container?.slice(0,12)||'未创建',p.last_success_at?new Date(p.last_success_at*1000).toLocaleString():'尚无成功调用',td=>link(td,'查看账号',p.slug)]);
  if(['/', '/auth-files','/routing','/oauth'].includes(path)){
   const s=section(main,path==='/routing'?'实际容器调度账号':'容器账号');table(s,['名称','编号','状态','容器','最近成功调用','操作'],accountRows());
   if(path==='/auth-files')el(s,'p','凭据保存在各自容器的数据盘中。刷新、浏览器和环境操作请进入对应账号；这里不提供凭据文件下载。','help');
   if(path==='/oauth')el(s,'p','新增授权从账号卡片打开容器浏览器。已授权账号可进入原浏览器，不会自动退出或重新授权。','help');
  }
  if(['/', '/routing','/config','/recommended-config'].includes(path)){
   const s=section(main,'正在使用的调度设置');table(s,['策略','请求重试','最多重试账号','会话绑定'],[[config.strategy||'未知',config.request_retry??'未知',config.max_retry_credentials===0?'原版默认':config.max_retry_credentials??'未知',config.session_affinity===true?'开启':config.session_affinity===false?'关闭':'未知']]);
   el(s,'p','路由策略和重试设置保存后，在下一次请求或状态检查时同步；沿用 CPA 原有选择和冷却逻辑。','help');
   if(config.refresh_workers_running!==config.refresh_workers_configured)el(s,'p','自动刷新并发配置与正在运行的并发不同，需要在维护时重启中央服务后生效。','bad');
   if(path==='/routing'){const a=el(s,'a','打开配置面板');a.href='/management.html#/config';a.onclick=e=>{e.preventDefault();navigate(a.href);};}
  }
  if(path==='/'||path==='/logs'){
   const live=section(main,'各账号执行状态');table(live,['账号','容器内活动请求','当前状态'],projects.map(p=>[td=>link(td,p.label||p.slug,p.slug),p.state?.active_calls??'未知',td=>el(td,'span',status(p),p.overall_ready?'ok':'bad')]));el(live,'p','在途请求由中央调度器统计；容器活动请求为执行器当前值，等待派发或重试时两者可能短暂不同。','help');
   const s=section(main,'请求与容器回执');el(s,'p',`累计请求 ${summary.requests??'未报告'} · 执行尝试 ${summary.attempts??'未报告'} · 成功尝试 ${summary.successful_attempts??'未报告'} · 失败尝试 ${summary.failed_attempts??'未报告'}`);
   const filter=el(s,'label','按账号查看：'),select=el(filter,'select');select.setAttribute('aria-label','按账号筛选请求');select.dataset.focusKey='account-filter';el(select,'option','全部账号').value='';for(const p of projects)el(select,'option',p.label||p.slug).value=p.slug;
   if(!projects.some(p=>p.slug===requestAccount))requestAccount='';select.value=requestAccount;select.onchange=()=>{requestAccount=select.value;render(data,path);};
   const rows=[];for(const r of data.requests||[])for(const a of r.attempts||[]){const slug=a.owner?.toLowerCase();if(requestAccount&&slug!==requestAccount)continue;const p=projects.find(p=>p.slug===slug);rows.push([r.run,a.id,td=>p?link(td,p.label||p.slug,p.slug):el(td,'span',a.owner),a.container?.slice(0,12)||'未派入',a.state,a.status??'—',a.response?.slice(0,16)||'未收到完整回执']);}
   table(s,['请求编号','尝试编号','账号','容器','状态','HTTP','回复摘要'],rows);el(s,'p','在最近 20 个请求中筛选；同一请求的重试保留各次尝试编号，点击账号可查看其用量和运行状态。失败与未完成回复不计入已确认用量。'+(path==='/logs'?'下方原生日志仍是中央运行日志。':''),'help');
  }
  if(path==='/'){
   const s=section(main,'用量与上游额度');table(s,['账号','已确认输入 Token','已确认输出 Token','成功完整记录','上游额度'],projects.map(p=>[td=>link(td,p.label||p.slug,p.slug),p.usage?.totals?.input_tokens??'未报告',p.usage?.totals?.output_tokens??'未报告',p.usage?.attempt_counts?.confirmed??0,(p.state?.quota_observation?.reported||p.state?.account_observation?.usage?.observed_at)?'已收到历史观测':'未报告']));
   el(s,'p','Token 统计来自完整模型回复，不代表订阅剩余额度。不主动查询上游。','help');
  }
  if(path==='/quota'){
   el(main,'p','显示最近收到的额度；自动读取本地记录，不主动查询上游。需要重新查询额度，请进入账号管理使用「刷新用量」。','help');
   const grid=el(main,'div',undefined,'quota-grid');
   if(!projects.length)el(grid,'p','暂无订阅账号。','help');
   for(const p of projects){
    const q=el(grid,'section',undefined,'quota-card');el(q,'p','Claude 订阅号 · '+subscriptionLabel(p.state),'help');el(q,'h2',p.label||p.slug);el(q,'span',status(p),p.overall_ready?'ok':'bad');
    renderAccountQuota(q,p);renderResetGrants(q,p);
    const detail=el(q,'details');detail.dataset.detailKey=p.slug;detail.open=openDetails.has(p.slug);el(detail,'summary','观测来源与 Token 统计');
    for(const item of accountQuotaWindows(p.state)){const stamp=new Date(item.stamp);el(detail,'p',item.label+' · '+item.source+' · '+(Number.isFinite(stamp.getTime())?stamp.toLocaleString():'尚无观测时间'),'help');}
    el(detail,'p','已确认输入 Token：'+(p.usage?.totals?.input_tokens??'未报告')+' · 输出：'+(p.usage?.totals?.output_tokens??'未报告')+' · 完整记录：'+(p.usage?.attempt_counts?.confirmed??0));
    el(detail,'p','Token 统计不代表订阅剩余额度；到重置时间后需等待新观测确认。','help');
    const capture=p.state?.account_observation?.capture;if(capture)el(detail,'p',capture.state==='complete'?'完整 HTTP 样本已加密保存 · '+capture.id:'HTTP 样本未完整保存，不能用于完整重放。',capture.state==='complete'?'help':'bad');
    link(q,'查看账号',p.slug);
   }
  }
  if(path==='/system'){
   const s=section(main,'模型与账号绑定');const models=new Map();for(const p of projects)for(const m of p.models||[]){if(!models.has(m))models.set(m,[]);models.get(m).push(p);}
   table(s,['模型','绑定账号','本地可接单账号数'],[...models].map(([m,ps])=>[m,ps.map(p=>p.label||p.slug).join('、'),ps.filter(p=>p.overall_ready).length]));el(s,'p','模型来自本地注册清单，不代表账号已经验证可调用。此页只读取已保存的状态，不主动探测上游。','help');
  }
  if(path==='/ai-providers')el(main,'p','订阅账号由独立容器管理，不计入下方原生供应商 API Key 数量。');
  el(main,'p','运行版本：'+(data.release?.candidate||'未知')+' · 管理界面 accounts-ui16 · 更新于 '+new Date().toLocaleTimeString(),'help');
  if(focused)[...view.querySelectorAll('[data-focus-key]')].find(e=>e.dataset.focusKey===focused)?.focus({preventScroll:true});
 }
 function reconcile(){const state=session.getState(),path=route(),key=state.isAuthenticated&&!isAccountPage()&&(names[path]||contextual[path])?path:'';const parent=nativeDocument.querySelector('.main-content');if(parent&&box.parentElement!==parent)parent.append(box);if(last===key)return;last=key;abort?.abort();clearInterval(timer);busy=false;box.hidden=true;view.replaceChildren();nativeDocument.documentElement.removeAttribute('data-container-page');if(!state.isAuthenticated)known=false;if(!key)return;abort=new AbortController();poll(key);timer=window.setInterval(()=>{if(!nativeDocument.hidden&&!view.activeElement?.matches('input,select,textarea'))poll(key);},5000);}
 async function poll(path){if(busy||path!==last)return;busy=true;const signal=abort.signal;try{const s=session.getState();if(new URL(s.apiBase).origin!==location.origin)return;const r=await window.fetch('/v8/management/account-environments/snapshot',{headers:{Authorization:'Bearer '+s.managementKey},credentials:'omit',cache:'no-store',redirect:'error',signal});if(r.status===401||r.status===403){session.getState().logout();return;}if(!r.ok)throw Error('容器状态读取失败，请稍后刷新。');const d=await r.json();if(signal.aborted||path!==last)return;if(!d.runtime_mode){known=false;box.hidden=true;view.replaceChildren();nativeDocument.documentElement.removeAttribute('data-container-page');return;}known=true;box.hidden=false;nativeDocument.documentElement.toggleAttribute('data-container-page',!!names[path]);render(d,path);}catch(e){if(signal.aborted||path!==last)return;box.hidden=false;view.replaceChildren();const p=el(view,'p','无法读取容器状态，请重试；未显示过期的账号数据。');p.setAttribute('role','alert');const retry=el(view,'button','重试读取状态');retry.onclick=()=>poll(path);nativeDocument.documentElement.toggleAttribute('data-container-page',known&&!!names[path]);}finally{if(!signal.aborted)busy=false;}}
 new MutationObserver(reconcile).observe(nativeDocument.getElementById('root'),{childList:true,subtree:true});window.addEventListener('hashchange',reconcile);window.addEventListener('popstate',reconcile);window.addEventListener('cpa:navigation',reconcile);session.subscribe(()=>{last='';reconcile();});reconcile();
})();

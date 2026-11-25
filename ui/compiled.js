(function accountConsole(session, theme) {
  'use strict';
  const nativeDocument = document;
  const host = nativeDocument.createElement('div');
  host.id = 'account-environments-app';
  host.dataset.uiRevision = 'accounts-ui2';
  const root = host.attachShadow({mode:'open'});
  nativeDocument.body.prepend(host);
  const bridgeStyle = nativeDocument.createElement('style');
  bridgeStyle.textContent = `html[data-account-console] .main-content > :not(#account-environments-app){display:none!important}
    html[data-account-console] .main-content{animation:none!important}
    html[data-account-console] .nav-item.active:not(#account-console-nav){background:transparent;box-shadow:none;border-color:transparent}
    #account-console-nav .nav-text{min-width:0}#account-console-nav .nav-label{white-space:normal}`;
  nativeDocument.head.append(bridgeStyle);
  function mountNavigation() {
    const authenticated = session.getState().isAuthenticated;
    nativeDocument.documentElement.toggleAttribute('data-account-console', authenticated && isAccountPage());
    if (!authenticated) { nativeDocument.getElementById('account-console-nav')?.remove(); return; }
    const reference = nativeDocument.querySelector('.sidebar a[href="#/auth-files"]');
    let entry = nativeDocument.getElementById('account-console-nav');
    if (reference && !entry) {
      entry = nativeDocument.createElement('a'); entry.id = 'account-console-nav'; entry.href = '/accounts.html#/';
      entry.title = '账号与运行状态';
      entry.innerHTML = '<span class="nav-icon"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 6.5h.01M7 17.5h.01M12 6.5h5M12 17.5h5"/></svg></span><span class="nav-text"><span class="nav-label">账号与运行状态</span></span>';
      entry.addEventListener('click', e => { if(e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return; e.preventDefault();nativeDocument.querySelector('.sidebar-backdrop.visible')?.click();navigate('/accounts.html#/'); });
      reference.before(entry);
    }
    if (entry) { entry.className = 'nav-item' + (isAccountPage() ? ' active' : ''); if(isAccountPage())entry.setAttribute('aria-current','page');else entry.removeAttribute('aria-current'); }
    const container = nativeDocument.querySelector('.main-content');
    if (container && host.parentElement !== container) container.append(host);
    nativeDocument.title = isAccountPage() ? '账号与运行状态 · CPA' : 'CPA';
  }
  const observer = new MutationObserver(mountNavigation);
  observer.observe(nativeDocument.getElementById('root'), {childList:true, subtree:true});
  nativeDocument.addEventListener('click', event => {
    if (!isAccountPage() || event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest?.('.sidebar a[href^="#/"]');
    if (link) { event.preventDefault(); event.stopPropagation(); nativeDocument.querySelector('.sidebar-backdrop.visible')?.click(); navigate('/management.html'+link.getAttribute('href')); }
  }, true);
  let dispose = () => {}, revision = 0;
  const isAccountPage = () => location.pathname === '/accounts.html';
  function navigate(url) {
    history.pushState(null, '', url);
    dispatchEvent(new PopStateEvent('popstate'));
  }
  function sync() {
    revision++;
    dispose();
    dispose = () => {};
    root.replaceChildren();
    const state = session.getState();
    const app = nativeDocument.getElementById('root');
    host.hidden = !state.isAuthenticated || !isAccountPage();
    if (app) app.hidden = false;
    mountNavigation();
    if (!state.isAuthenticated || !isAccountPage()) return;
    root.innerHTML = '<style>:host{display:block;color:var(--text-primary,#2d2a26);font:14px/1.6 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;font-variant-numeric:tabular-nums;color-scheme:inherit}:host([hidden]),[hidden]{display:none!important}*{box-sizing:border-box}body{margin:0}main{max-width:1180px;margin:0 auto;padding:26px 8px 48px}h1,h2,h3,p{margin:0}h1{font-size:28px;line-height:1.3;letter-spacing:-.025em;font-weight:680}h2{font-size:17px;font-weight:650}h3{font-size:14px;font-weight:650}p{overflow-wrap:anywhere}.subtitle,.muted,.help,.summary-note{color:var(--text-secondary,#6d6760)}.subtitle{margin-top:8px}.help{font-size:13px;max-width:75ch}.page-heading,.section-heading,.list-heading,.card-heading,.form-footer{display:flex;align-items:center;justify-content:space-between;gap:20px}.heading-actions,.actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center}button,.button-link{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:40px;padding:8px 16px;border:1px solid transparent;border-radius:8px;background:var(--text-primary,#2d2a26);color:var(--bg-primary,#fff);font:600 13px/1.5 system-ui;cursor:pointer;text-decoration:none;transition:background .15s,color .15s,border-color .15s}button:hover,.button-link:hover{opacity:.85}button:active{transform:translateY(1px)}button:disabled{opacity:.5;cursor:not-allowed}.secondary{background:var(--bg-primary,#fff);color:var(--text-primary,#2d2a26);border-color:var(--border-color,#e5e5e5)}.quiet{background:transparent;color:var(--text-secondary,#6d6760);padding:6px 10px}.quiet:hover,.secondary:hover{background:var(--bg-tertiary,#f6f6f6);opacity:1}button:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible,a:focus-visible{outline:2px solid var(--text-primary,#2d2a26);outline-offset:3px}input,select{font:inherit;color:var(--text-primary,#2d2a26);background:var(--bg-primary,#fff);border:1px solid var(--border-color,#e5e5e5);border-radius:8px;min-height:42px;padding:9px 12px;width:100%;caret-color:var(--text-primary,#2d2a26)}input::placeholder{color:var(--text-secondary,#6d6760);opacity:1}label{display:block;font-size:13px;font-weight:550}label input,label select{margin-top:7px;font-weight:400}.overview{display:flex;gap:26px;align-items:center;flex-wrap:wrap;margin:28px 0 26px;padding:17px 0;border-top:1px solid var(--border-color,#e5e5e5);border-bottom:1px solid var(--border-color,#e5e5e5);color:var(--text-secondary,#6d6760);font-size:13px}.overview>span{display:flex;gap:8px;align-items:center}.overview strong{color:var(--text-primary,#2d2a26);font-size:16px;font-weight:650}.overview #status{margin-left:auto;font-size:12px}.dot{display:inline-block;width:6px;height:6px;border-radius:50%;background:var(--text-secondary,#6d6760)}.good-dot{background:var(--success-color,#249568)}.warning-dot{background:var(--warning-color,#bd8135)}.progress:empty{display:none}.progress{padding:12px 16px;margin:0 0 20px;border-radius:8px;background:var(--bg-tertiary,#f6f6f6)}.add-panel{border:1px solid var(--border-color,#e5e5e5);border-radius:12px;padding:22px;margin-bottom:28px;background:var(--bg-secondary,#fff)}.section-heading{align-items:flex-start;margin-bottom:20px}.section-heading p{color:var(--text-secondary,#6d6760);font-size:13px;margin-top:4px}.account-fields{display:grid;grid-template-columns:1fr 1fr 1fr;gap:18px}.account-fields+.help{margin-top:10px}.form-footer{justify-content:flex-start;margin-top:20px}.form-footer p{font-size:13px}.list-heading{margin-bottom:16px}.list-heading h2{font-size:16px}.list-heading h2 span{font-weight:400;margin-left:5px}.search{width:240px}.search input{min-height:38px;margin:0;font-size:13px}#accounts{display:grid;gap:16px}.account-card{border:1px solid var(--border-color,#e5e5e5);border-radius:12px;background:var(--bg-secondary,#fff);overflow:hidden}.card-main{padding:22px 24px}.card-heading{align-items:flex-start}.account-title h2{font-size:17px}.account-title .muted{font-size:12px;margin-top:3px}.badge{display:inline-flex;align-items:center;gap:6px;padding:4px 9px;border-radius:6px;white-space:nowrap;font-size:12px;font-weight:550;background:var(--bg-tertiary,#f6f6f6);color:var(--text-secondary,#6d6760)}.badge.good{background:var(--success-badge-bg,#d1fae5);color:var(--success-badge-text,#065f46)}.badge.warning{background:var(--warning-badge-bg,#fff1d6);color:var(--warning-badge-text,#80530b)}.card-facts{display:grid;grid-template-columns:1fr 1fr 1fr;gap:18px;margin:20px 0}.card-facts dt{font-size:12px;color:var(--text-secondary,#6d6760);margin-bottom:3px}.card-facts dd{margin:0;font-size:13px;overflow-wrap:anywhere}.card-notice{font-size:13px;color:var(--text-secondary,#6d6760);margin-bottom:16px}.card-notice:empty{display:none}.actions{margin-top:18px}.proxy-entry{max-width:560px;margin-top:18px}.account-detail{border-top:1px solid var(--border-color,#e5e5e5);padding:0 24px}.account-detail>summary{min-height:44px;font-size:12px;color:var(--text-secondary,#6d6760)}.detail-content{display:grid;grid-template-columns:1fr 1fr;gap:24px 36px;padding:6px 0 24px}.detail-content section{min-width:0}.detail-content h3{margin-bottom:8px}.detail-content p{font-size:13px;line-height:1.75;color:var(--text-secondary,#6d6760);margin-top:4px}.detail-actions{grid-column:1/-1;display:flex;gap:8px;flex-wrap:wrap}.empty{display:flex;flex-direction:column;align-items:center;text-align:center;padding:50px 24px 54px;border:1px dashed var(--border-color,#e5e5e5);border-radius:12px}.empty svg{width:36px;height:36px;color:var(--text-secondary,#6d6760);margin-bottom:16px}.empty h3{font-size:17px}.empty p{color:var(--text-secondary,#6d6760);max-width:46ch;margin-top:8px}.empty button{margin-top:22px}.onboarding{display:flex;align-items:center;gap:18px;margin-top:22px;font-size:12px;color:var(--text-secondary,#6d6760)}.onboarding span{display:flex;gap:7px;align-items:center}.onboarding b{border:1px solid var(--border-color,#e5e5e5);border-radius:50%;width:22px;height:22px;display:grid;place-items:center;font-size:11px;font-weight:500}.support-section{margin-top:24px;border-top:1px solid var(--border-color,#e5e5e5)}summary{cursor:pointer;padding:16px 0;font-size:14px;font-weight:550}summary::marker{color:var(--text-secondary,#6d6760)}.summary-note{font-size:12px;font-weight:400;margin-left:10px}.settings{display:flex;gap:20px;align-items:center;flex-wrap:wrap;padding:8px 0 18px}.settings>div{flex:1;min-width:220px}.settings h2{font-size:14px}.settings p{font-size:13px;color:var(--text-secondary,#6d6760);margin-top:6px;max-width:65ch}.settings>#logging-status{flex-basis:100%;margin:0}.toggle{display:flex;align-items:center;gap:10px;cursor:pointer}.toggle input{appearance:none;flex-shrink:0;width:36px;height:22px;min-height:22px;padding:0;margin:0;border-radius:20px;background:var(--bg-tertiary,#f6f6f6);position:relative}.toggle input:before{content:"";position:absolute;top:2px;left:2px;width:16px;height:16px;border-radius:50%;background:var(--text-secondary,#6d6760);transition:left .15s}.toggle input:checked{background:var(--text-primary,#2d2a26);border-color:transparent}.toggle input:checked:before{left:16px;background:var(--bg-primary,#fff)}.runtime-info{padding:14px 0;border-top:1px solid var(--border-color,#e5e5e5);font-size:12px;color:var(--text-secondary,#6d6760)}.runtime-info p+p{margin-top:6px}#requests{padding:0 0 18px;color:var(--text-secondary,#6d6760);font-size:13px}#requests article{padding:16px 0;border-top:1px solid var(--border-color,#e5e5e5)}#requests h3{margin-bottom:6px}.loading{padding:40px;color:var(--text-secondary,#6d6760);background:var(--bg-tertiary,#f6f6f6);border-radius:12px}.error{color:var(--danger-color,#b42318)}a{color:inherit;text-underline-offset:3px}::selection{background:var(--text-primary,#2d2a26);color:var(--bg-primary,#fff)}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}@media(min-width:1500px){#accounts{grid-template-columns:repeat(2,minmax(0,1fr))}.empty,.loading{grid-column:1/-1}}@media(max-width:900px){main{padding:20px 0 36px}.page-heading{align-items:flex-start;flex-direction:column;gap:18px}.overview{gap:18px}.overview #status{width:100%;margin-left:0}.account-fields{grid-template-columns:1fr 1fr}.account-fields>label:last-child{grid-column:1/-1}.detail-content{grid-template-columns:1fr}.card-facts{gap:14px}.summary-note{display:none}}@media(max-width:520px){h1{font-size:24px}.heading-actions{width:100%}.heading-actions button{flex:1}.list-heading{align-items:stretch;flex-direction:column;gap:10px}.search{width:100%}.card-main{padding:18px}.card-heading{gap:10px}.card-facts{grid-template-columns:1fr 1fr}.card-facts>div:last-child{grid-column:1/-1}.account-detail{padding:0 18px}.account-fields{grid-template-columns:1fr}.account-fields>label:last-child{grid-column:auto}.add-panel{padding:18px}.form-footer{align-items:flex-start;flex-direction:column}.onboarding{gap:10px;flex-wrap:wrap;justify-content:center}.empty{padding:32px 16px}.actions button,.actions .button-link{min-height:44px}.overview{column-gap:18px;row-gap:10px}.badge{white-space:normal;flex-shrink:0;max-width:45%}}@media(prefers-reduced-motion:reduce){*{transition:none!important}}:host-context([data-theme="dark"]) .error{color:#f1a79a}.creation-progress{margin:18px 0;padding:16px 0;border-top:1px solid var(--border-color,#e5e5e5);border-bottom:1px solid var(--border-color,#e5e5e5)}.creation-heading{display:flex;gap:10px;justify-content:space-between;align-items:center}.creation-heading>span{font-size:12px}.creation-progress summary{font-size:12px;padding:12px 0;color:var(--text-secondary,#6d6760)}.creation-steps{list-style:none;margin:0;padding:0;display:grid;gap:10px}.creation-steps li{display:flex;gap:12px;align-items:center;justify-content:space-between;font-size:12px;position:relative;padding-left:18px}.creation-steps li:before{content:"";width:7px;height:7px;border-radius:50%;position:absolute;left:0;background:var(--border-color,#e5e5e5)}.creation-steps .step-completed:before{background:var(--success-color,#249568)}.creation-steps .step-running:before{background:var(--text-primary,#2d2a26)}.creation-steps .step-failed:before{background:var(--error-color,#b42318)}.step-pending{color:var(--text-secondary,#6d6760)}.step-running{font-weight:650}.step-result{display:flex;gap:10px;flex-shrink:0}.step-result time{color:var(--text-secondary,#6d6760)}.creation-error{font-size:13px;margin-top:10px;color:var(--error-color,#b42318)}.creation-progress .help{margin-top:14px}.creation-submitting{font-size:13px;margin-top:12px}:host-context([data-theme="dark"]) .creation-error{color:#f1a79a}@media(max-width:520px){.creation-heading{align-items:flex-start;flex-direction:column}.step-result{gap:5px}.step-result time{font-size:11px}}</style>';
    const page = nativeDocument.createElement('section');
    page.innerHTML = "<main>\n  <header class=\"page-heading\"><div><h1>账号与运行状态</h1><p class=\"subtitle\">管理独立账号环境，查看授权与接单状态。</p></div><div class=\"heading-actions\"><button id=\"refresh\" class=\"secondary\">刷新状态</button><button id=\"add-account\" aria-expanded=\"false\" aria-controls=\"account-add\">添加账号</button></div></header>\n  <div class=\"overview\" aria-label=\"账号概览\"><span>全部账号 <strong id=\"count-all\">—</strong></span><span><i class=\"dot good-dot\"></i>可接单 <strong id=\"count-ready\">—</strong></span><span><i class=\"dot warning-dot\"></i>待处理 <strong id=\"count-pending\">—</strong></span><span id=\"status\" role=\"status\">正在读取状态…</span></div>\n  <p id=\"progress\" class=\"progress\" role=\"status\"></p>\n  <section id=\"account-add\" class=\"add-panel\" hidden aria-labelledby=\"add-title\"><div class=\"section-heading\"><div><h2 id=\"add-title\">添加账号</h2><p>保存后，为此账号绑定代理并创建独立容器。</p></div><button id=\"cancel-add\" class=\"quiet\" type=\"button\">收起</button></div><form id=\"account-form\"><div class=\"account-fields\"><label for=\"account-label\">显示名称<input id=\"account-label\" name=\"label\" required maxlength=\"60\" autocomplete=\"off\" placeholder=\"例如：研发账号\"></label><label for=\"account-id\">账号编号<input id=\"account-id\" name=\"slug\" required pattern=\"[a-z](?:[a-z0-9\\-]{0,30}[a-z0-9])?\" maxlength=\"32\" autocomplete=\"off\" spellcheck=\"false\" placeholder=\"例如：research-01\" aria-describedby=\"account-id-help\"></label><label for=\"account-provider\">通道<select id=\"account-provider\" required disabled><option value=\"\">正在读取…</option></select></label></div><p id=\"account-id-help\" class=\"help\">编号使用小写字母、数字和中划线，创建后与账号环境绑定。</p><div class=\"form-footer\"><button id=\"account-submit\" type=\"submit\">保存并继续</button><p id=\"account-feedback\" role=\"status\"></p></div></form></section>\n  <div class=\"list-heading\"><h2>账号 <span id=\"list-count\" class=\"muted\"></span></h2><label class=\"search\"><span class=\"sr-only\">搜索账号</span><input id=\"account-search\" type=\"search\" placeholder=\"搜索名称或编号\" autocomplete=\"off\"></label></div>\n  <section id=\"accounts\" aria-label=\"账号列表\"><div class=\"loading\">正在读取账号与容器状态…</div></section>\n  <details class=\"support-section\" id=\"request-details\"><summary>请求与重试记录 <span class=\"summary-note\">查看请求经过的账号与容器</span></summary><section id=\"requests\"></section></details>\n  <details class=\"support-section\" id=\"console-settings\"><summary>运行设置与版本 <span class=\"summary-note\" id=\"logging-summary\">日志设置、版本与运行模式</span></summary><section class=\"settings\" aria-labelledby=\"logging-title\"><div><h2 id=\"logging-title\">文件日志</h2><p id=\"logging-help\">记录 CPA 运行日志，修改后自动生效。关闭不会删除已有日志，也不会开启请求正文日志。</p></div><label class=\"toggle\"><input id=\"logging-toggle\" type=\"checkbox\" role=\"switch\" aria-describedby=\"logging-help logging-status\" disabled><span>启用文件日志</span></label><p id=\"logging-status\" role=\"status\">正在读取设置…</p></section><div class=\"runtime-info\"><p id=\"version\"></p><p id=\"runtime-mode\"></p><p class=\"help\">真实订阅授权与模型调用仍需实际账号验收。环境备份、容器运行和中央接单资格分别检查。</p></div></details>\n</main>";
    root.append(page);
    nativeDocument.title = '账号与运行状态 · CPA';
    const generation = revision, controller = new AbortController(), timers = [];
    dispose = () => { controller.abort(); timers.forEach(clearInterval); };
    const document = {
      querySelector: q => page.querySelector(q),
      querySelectorAll: q => page.querySelectorAll(q),
      createElement: (...args) => nativeDocument.createElement(...args),
      get activeElement() { return root.activeElement; },
      get hidden() { return nativeDocument.hidden; }
    };
    const setInterval = (fn, delay) => { const id = window.setInterval(fn, delay); timers.push(id); return id; };
    const sessionStorage = {getItem: () => 'native-management-session'};
    async function fetch(path, options = {}) {
      const current = session.getState();
      if (generation !== revision || !current.isAuthenticated) throw Error('管理会话已结束，请重新登录。');
      let target;
      try { target = new URL(current.apiBase); } catch { throw Error('管理服务地址无效，请返回首页重新连接。'); }
      if (target.origin !== location.origin) throw Error('请在当前 CPA 的管理地址打开账号页面。');
      const endpoint = path === '/snapshot' ? 'snapshot' : path === '/action' ? 'action' : null;
      if (!endpoint) throw Error('不支持的管理操作。');
      const response = await window.fetch('/v8/management/account-environments/' + endpoint, {
        method: options.method || 'GET', body: options.body, signal: controller.signal,
        credentials:'omit', cache:'no-store', redirect:'error',
        headers:{'Content-Type':'application/json', Authorization:'Bearer ' + current.managementKey}
      });
      if (generation !== revision) throw Error('管理会话已结束。');
      if (response.status === 401 || response.status === 403) {
        session.getState().logout();
        throw Error('管理登录已失效，请重新登录。');
      }
      return response;
    }
    /* Read-only presentation of the native CPA snapshot; no accounting or routing. */
function quotaLines(observation) {
 const entries=Object.entries(observation?.signals||{});
 if(!observation?.reported||!entries.length)return ['上游尚未上报额度信息；本次 Token 统计不代表订阅剩余额度。'];
 const headers=Object.fromEntries(entries.map(([k,v])=>[k.toLowerCase(),v]));
 const stamp=new Date(observation.observed_at);
 const lines=['最近观测：'+(Number.isFinite(stamp.getTime())?stamp.toLocaleString():'时间未知')+'；这是历史观测，并非实时余额。'];
 for(const [window,label] of [['5h','5 小时窗口'],['7d','7 天窗口']]) {
  const prefix='anthropic-ratelimit-unified-'+window+'-';
  const raw=headers[prefix+'utilization'];
  if(raw!==undefined) {
   const ratio=Number(raw);
   lines.push(label+'已用：'+(String(raw).trim()!==''&&Number.isFinite(ratio)&&ratio>=0&&ratio<=1?Number((ratio*100).toFixed(2))+'%':'未能解释（原值：'+raw+'）'));
  }
  const reset=headers[prefix+'reset'];
  if(reset!==undefined){const date=new Date(Number(reset)*1000);lines.push(label+'重置时间：'+(/^[0-9]+$/.test(reset)&&Number.isFinite(date.getTime())?date.toLocaleString():'未能解释（原值：'+reset+'）'));}
 }
 lines.push('上游原始额度字段（仅展示，不据此修改派单）：');
 for(const [name,value] of entries.sort(([a],[b])=>a.localeCompare(b)))lines.push(name+'：'+value);
 return lines;
}
if(typeof module!=='undefined')module.exports={quotaLines};


    'use strict';
let loggingSaving=false;
function renderLogging(value){
 if(loggingSaving)return;
 const summary=document.querySelector('#logging-summary');if(summary)summary.textContent=typeof value==='boolean'?(value?'文件日志已开启':'文件日志已关闭'):'日志状态待确认';
 const control=document.querySelector('#logging-toggle');
 control.disabled=typeof value!=='boolean';
 control.indeterminate=typeof value!=='boolean';
 if(typeof value==='boolean')control.checked=value;
 document.querySelector('#logging-status').textContent=typeof value==='boolean'?(value?'已开启文件日志':'已关闭文件日志'):'暂时无法读取日志设置，请刷新重试。';
}
document.querySelector('#logging-toggle').addEventListener('change',async event=>{
 const control=event.target,wanted=control.checked,previous=!wanted;
 loggingSaving=true;control.disabled=true;
 const status=document.querySelector('#logging-status');status.textContent='正在保存日志设置…';
 try{
  const response=await fetch('/action',{method:'POST',headers:{'Content-Type':'application/json','X-Offline-View':sessionStorage.getItem('native-refresh-view')},body:JSON.stringify({action:'logging-update',value:wanted})});
  if(!response.ok)throw Error('save_failed');
  // Read the actual setting back instead of presenting an optimistic success.
  const check=await fetch('/snapshot',{headers:{'X-Offline-View':sessionStorage.getItem('native-refresh-view')}});
  if(!check.ok)throw Error('readback_failed');
  const result=await check.json();
  if(result.logging_to_file!==wanted)throw Error('readback_mismatch');
  control.checked=wanted;const summary=document.querySelector('#logging-summary');if(summary)summary.textContent=wanted?'文件日志已开启':'文件日志已关闭';status.textContent=wanted?'已开启文件日志；无需重启。':'已关闭文件日志；已有日志保留。';
 }catch(error){
  control.checked=previous;control.indeterminate=true;
  status.textContent='未能确认设置是否保存，请刷新读取实际状态后重试。';
 }finally{loggingSaving=false;control.disabled=control.indeterminate;}
});


    /* Creation events are recorded by the controller, never inferred from a timer. */
const creationErrors = {
 invalid_proxy_config:'SOCKS 地址格式不正确，请检查协议、IP、端口和用户名密码。',
 proxy_auth_method_rejected:'代理不接受当前认证方式，请确认它支持 SOCKS5 用户名密码认证。',
 proxy_auth_rejected:'SOCKS 认证被拒绝，请检查代理用户名、密码或服务端访问限制。',
 proxy_connect_rejected:'SOCKS 连接目标被拒绝，请检查代理是否允许访问出口检测服务。',
 proxy_connection_failed:'无法建立代理连接，或连接中途断开，请检查代理地址、端口与可用状态。',
 proxy_check_timeout:'代理检查超时，请检查代理是否在线；没有改为直连。',
 network_guard_setup_failed:'网络隔离规则设置失败，已停止创建，请检查容器引擎。',
 exit_tls_failed:'出口检测的 HTTPS 校验失败，已停止创建。',
 exit_timezone_unavailable:'未能获取有效的公网出口和时区，请检查代理能否访问出口检测服务。',
 probe_runtime_failed:'网络检测容器运行失败，请检查容器引擎和镜像。',
 account_card_exists_no_reinitialize:'已有环境记录，已阻止重复初始化。请先检查保留的环境，不能覆盖重建。',
 environment_inventory_failed:'运行环境信息读取失败，请检查镜像与本地容器引擎。',
 storage_prepare_failed:'账号数据盘准备失败，请检查磁盘容量与容器存储。',
 network_save_failed:'代理设置写入账号数据盘失败，已有数据保留。',
 environment_initialize_failed:'环境初始化或初始备份失败，已有数据保留。',
 container_create_failed:'账号容器创建失败，已有环境记录保留。',
 container_start_failed:'容器未能正常启动，请检查启动日志；不要重复初始化。',
 container_readiness_failed:'容器已提交启动，但网络或执行器尚未就绪，请检查运行状态。',
 creation_interrupted:'上次创建过程被服务重启或中断打断，已保留环境记录，请先检查现有状态。',
 creation_failed:'创建未完成，请查看失败步骤；已有数据不会自动删除。'
};
const creationStages = [
 ['checking_socks','检查 SOCKS 连接与认证'], ['checking_exit','检查公网出口与时区'],
 ['reading_environment','读取容器环境信息'], ['preparing_storage','准备账号数据盘'],
 ['saving_network','保存代理与时区设置'], ['initializing_environment','初始化环境与初始备份'],
 ['creating_container','创建账号容器'], ['starting_container','启动容器'],
 ['waiting_for_worker','检查网络与执行器就绪']
];
function renderCreation(parent,p) {
 const record=p.protection||{};
 if(!record.creation_steps?.length&&!['creating','creation_failed'].includes(record.phase))return;
 const block=text(parent,'section','','creation-progress');block.setAttribute('aria-label','创建进度');
 const failed=record.phase==='creation_failed',running=record.phase==='creating';
 const header=text(block,'div','','creation-heading');text(header,'h3',failed?'创建失败':running?'正在创建环境':'环境启动完成');
 const steps=record.creation_steps||[],current=steps.find(s=>s.status==='running');
 text(header,'span',running?(creationStages.find(([key])=>key===current?.step)?.[1]||'正在准备…'):failed?'请查看下方原因':record.phase==='awaiting_authorization'?'等待浏览器授权':'创建记录','muted');
 if(failed)text(block,'p',creationErrors[record.creation_error]||'上次创建未完成，旧版本没有保存具体原因。再次检查后会显示失败步骤。','creation-error');
 const details=text(block,'details','');details.open=running||failed;text(details,'summary','查看创建过程');
 const list=text(details,'ol','','creation-steps');
 for(const [key,label] of creationStages){
  const event=steps.find(s=>s.step===key),state=event?.status||'pending';
  const item=text(list,'li','','step-'+state);text(item,'span',label);
  const tail=text(item,'span','','step-result');text(tail,'span',{completed:'已完成',running:'进行中',failed:'失败',pending:'等待'}[state]);
  if(event?.started_at){const date=new Date(event.started_at*1000),t=text(tail,'time',date.toLocaleTimeString());t.dateTime=date.toISOString();}
 }
 if(running)text(block,'p','过程会自动更新，可保持页面打开。','help');
}

    'use strict';
const tokenKey='native-refresh-view';const pending={};const proxies={};const viewers={};let trackedAuthorization='';let working=false;
const labels={account_ready:'可接单',invalid_account_id:"账号编号格式有误，请使用小写英文字母、数字和中划线，末尾不能为中划线",invalid_account_label:"显示名称须为 1—60 个字符，不能含首尾空格或控制字符",provider_not_available:"当前运行配置不支持该提供方，请检查配置",account_already_registered:"该编号已绑定其他账号记录，请使用新的编号",account_not_registered:"未找到账号记录，请先添加账号",browser_sandbox_unavailable:"浏览器安全隔离检查未通过，窗口已关闭；请检查容器安全规则",browser_start_failed:"容器浏览器启动失败，请检查浏览器运行环境",stop_account_before_restore:"请先停止该账号容器再恢复，当前数据不会被覆盖",backup_card_changed:"备份不属于当前账号环境，已拒绝恢复",backup_package_changed:"备份文件发生变化，已拒绝恢复",backup_credentials_older_than_local:"备份凭据比本地旧，已拒绝覆盖",backup_restore_failed:"备份校验或恢复未完成，原账号数据已保留",account_proxy_unavailable:"账号代理或出口检查失败，已停派",network_status_unknown:"网络检查状态无法确认，已停派",environment_backup_required:'环境备份未通过，暂不派单',environment_protection_unknown:'环境保护状态无法确认，暂不派单',missing:'尚未创建',container_stopped:'容器已停止',worker_unavailable:'执行器不可用',binding_check_failed:'容器或数据盘归属检查失败',credential_save_failed:'凭据保存失败',offline_ready:'离线测试可接单',authorization_pending:'正在等待授权',authorization_required:'需要授权',credential_expired:'访问凭据已到期，已停派',credential_rejected:'访问凭据被拒，已停派',account_disabled:'账号已停用',account_unavailable:'账号不可用或冷却中'};
Object.assign(labels,creationErrors);
const protectionLabels={not_created:'尚未创建',creating:'正在准备账号环境与初始备份',creation_failed:'创建未完成，需要检查环境',awaiting_authorization:'初始环境备份完成，等待授权',authorizing:'正在等待授权',exchanging_credentials:'正在保存授权凭据',authorization_failed:'授权未完成',closing_browser:'正在关闭浏览器',saving_backup:'正在保存授权后环境',verifying_backup:'正在校验完整备份',starting_protected_environment:'正在恢复执行器',ready:'环境与备份校验通过',backup_failed:'备份未完成，可重试，不需要重新授权',checking_restore:'正在检查恢复条件',recovery_check_failed:'恢复检查未通过，已停派'};
const authorizationLabels={authorization_cancelled:'已取消授权',authorization_expired:'授权等待已超时',authorization_denied:'已在授权页面取消',authorization_exchange_failed:'授权信息交换未完成'};
const renewalLabels={sign_in_required:'续期需要登录；服务状态单独判断',expired_sign_in_required:'凭据不可用，需要登录',retry_scheduled:'刷新失败，已安排重试',renewal_verified:'最近刷新成功',awaiting_first_renewal:'尚未刷新'};
const results={preparing:'正在检查执行条件',not_dispatched:'未派入容器',running:'执行中',completed:'执行已完成',result_unknown:'执行结果待确认'};
const stops={environment_backup_required:"环境备份未通过，未派入容器",environment_protection_unknown:"环境保护状态无法确认，未派入容器",client_disconnected:'客户端已断开，已请求停止',controller_stopping:'控制服务正在停止',execution_interrupted:'执行链路中断',client_delivery_incomplete:'执行已完成，客户端接收不完整'};
const status=document.querySelector('#status'),accounts=document.querySelector('#accounts');let busy=false;
function text(parent,tag,value,className){const e=document.createElement(tag);e.textContent=value;if(className)e.className=className;parent.append(e);return e;}
function detail(parent,title){const section=text(parent,'section','');text(section,'h3',title);return section;}
function fact(parent,label,value){const group=text(parent,'div','');text(group,'dt',label);text(group,'dd',value);}
function showAdd(open=true){const panel=document.querySelector('#account-add');panel.hidden=!open;document.querySelector('#add-account').setAttribute('aria-expanded',String(open));if(open)document.querySelector('#account-label').focus();else document.querySelector('#add-account').focus();}
const expandedAccounts=new Set();let currentProjects=[];
function filterAccounts(){const q=document.querySelector('#account-search').value.trim().toLocaleLowerCase();let shown=0;for(const card of accounts.querySelectorAll('.account-card')){card.hidden=!card.dataset.search.includes(q);if(!card.hidden)shown++;}const empty=document.querySelector('#search-empty');if(empty)empty.hidden=!currentProjects.length||shown>0;}
document.querySelector('#add-account').onclick=()=>showAdd();document.querySelector('#cancel-add').onclick=()=>showAdd(false);document.querySelector('#account-search').addEventListener('input',filterAccounts);
function renderCard(p,data){
 const card=text(accounts,'article','','account-card');card.dataset.account=p.slug;card.dataset.search=((p.label||'')+' '+p.slug).toLocaleLowerCase();
 const main=text(card,'div','','card-main'),heading=text(main,'div','','card-heading'),title=text(heading,'div','','account-title');
 text(title,'h2',p.label||p.slug);text(title,'p',p.slug+' · '+(data.providers?.[p.provider]?.label||p.provider),'muted');
 const needsAuth=['authorization_required','authorization_pending'].includes(p.reason);
 text(heading,'span',p.overall_ready?'可接单':p.protection?.phase==='creating'?'创建中':p.protection?.phase==='creation_failed'?'创建失败':p.reason==='missing'?'待创建环境':p.reason==='authorization_pending'?'等待授权':p.reason==='authorization_required'?'需要授权':'暂停接单','badge '+(p.overall_ready?'good':p.reason==='missing'?'':'warning'));
 const protection=p.protection||{phase:'not_created'},backup=p.portable_backup,central=p.central_dispatch||{reason:'unknown'};
 const centralLabels={eligible:'调度条件满足',cooldown:'中央冷却中',disabled:'中央已停用',unavailable:'中央暂不可用',unknown:'中央状态无法读取'};
 const facts=text(main,'dl','','card-facts');fact(facts,'容器状态',p.protection?.phase==='creating'?'正在准备环境':p.protection?.phase==='creation_failed'?'创建未完成':p.reason==='missing'?'尚未创建':labels[p.reason]||'状态待确认');fact(facts,'账号网络',p.network?(p.network.healthy?'检查通过':'检查未通过'): '等待检查');fact(facts,'活动请求',p.state?.active_calls??'—');
 const notice=protection.phase==='creating'?'正在准备此账号的独立运行环境，请查看下方进度。':protection.phase==='creation_failed'?'创建未完成，请查看下方失败步骤与原因。':p.reason==='missing'?'绑定 SOCKS 后创建此账号的独立运行环境。':needsAuth?'在容器浏览器内完成授权，完成后自动关闭浏览器并保存环境。':!p.overall_ready?(labels[p.reason]||centralLabels[central.reason]||'请展开详情查看原因。'):'';
 text(main,'p',notice,'card-notice');
 if(p.network?.timezone_warning)text(main,'p',p.network.timezone_check_reason==='timezone_changed'?'出口时区与固定时区不同；继续使用 '+p.network.fixed_timezone+'。':'本次未能核对出口时区；继续使用已保存的时区。','card-notice');
 if(p.state?.authorization_issue)text(main,'p',authorizationLabels[p.state.authorization_issue]||'授权未完成，请查看详情。','error');
 if(p.state?.storage_warning)text(main,'p','凭据保存或备份异常，请检查存储；有效调用继续按 CPA 原逻辑处理。','error');
 renderCreation(main,p);
 const actions=text(main,'div','','actions');
 if(p.reason==='missing'&&['not_created','creation_failed'].includes(protection.phase)){
  const label=text(main,'label','账号 SOCKS 地址','proxy-entry'),input=document.createElement('input');input.type='password';input.autocomplete='off';input.placeholder='socks5h://用户名:密码@IP:端口';input.value=proxies[p.slug]||'';input.dataset.owner=p.slug;input.addEventListener('input',()=>proxies[p.slug]=input.value);label.append(input);main.append(actions);
 }
 function action(parent,operation,label,secondary=false){const b=text(parent,'button',label,secondary?'secondary':'');b.dataset.focusId=p.slug+':'+operation;b.disabled=working;b.addEventListener('click',()=>operate(p.slug,operation));return b;}
 if(p.reason==='missing'&&['not_created','creation_failed'].includes(protection.phase))action(actions,'create','校验代理并创建容器');
 if(p.reason==='authorization_required')action(actions,'auth-begin','打开浏览器授权');
 if(p.reason==='authorization_pending'){
  if(viewers[p.slug]){const link=text(actions,'a','进入容器浏览器','button-link');link.href=viewers[p.slug];link.target='_blank';link.rel='noreferrer noopener';}
  action(actions,'open-browser','展开 / 重新进入浏览器',!!viewers[p.slug]);action(actions,'auth-cancel','取消授权',true);
 }
 if(p.reason==='container_stopped')action(actions,'restart','重启容器');
 if(p.reason==='account_proxy_unavailable')action(actions,'restart','重新检查网络');
 if(['backup_failed','recovery_check_failed'].includes(protection.phase)||(p.state?.authorized&&!protection.backup_verified))action(actions,'retry-backup','重试环境备份');
 if(!actions.children.length)actions.hidden=true;
 const details=text(card,'details','','account-detail');text(details,'summary','环境、授权与用量详情').dataset.focusId=p.slug+':details';details.open=expandedAccounts.has(p.slug);details.addEventListener('toggle',()=>{if(details.isConnected){if(details.open)expandedAccounts.add(p.slug);else expandedAccounts.delete(p.slug);}});
 const content=text(details,'div','','detail-content');let section=detail(content,'环境与网络');
 text(section,'p','容器编号：'+(p.container?p.container.slice(0,12):'未创建'));text(section,'p','中央调度：'+(centralLabels[central.reason]||'未知'));
 if(central.retry_after)text(section,'p','下次可重试：'+new Date(central.retry_after).toLocaleString());
 if(p.network){text(section,'p',p.network.healthy?'启动网络检查通过；不进行定时公网出口探测。':'网络检查未通过或本地监督失联，已暂停新任务。');if(p.network.fixed_timezone)text(section,'p','固定时区：'+p.network.fixed_timezone+' · 系统与浏览器语言：英语');if(p.network.observed_timezone&&p.network.timezone_warning)text(section,'p','本次出口时区：'+p.network.observed_timezone);if(p.network.network_checked_at)text(section,'p','启动检查：'+new Date(p.network.network_checked_at*1000).toLocaleString());if(p.network.last_success_at)text(section,'p','最近检查成功：'+new Date(p.network.last_success_at*1000).toLocaleString());if(p.network.checking)text(section,'p','正在检查代理和公网出口…');}
 if(p.exit_code!==undefined)text(section,'p','容器退出码：'+p.exit_code);
 section=detail(content,'授权与凭据');
 if(p.state){text(section,'p','凭据修订：'+p.state.revision);text(section,'p','刷新：'+(p.state.refreshing?'正在刷新，有效凭据继续服务':renewalLabels[p.state.renewal_state]||'空闲'));for(const [key,label] of [['expires','到期时间'],['last_refresh','最近刷新'],['next_refresh','最早下次检查']])if(p.state[key])text(section,'p',label+'：'+new Date(p.state[key]).toLocaleString());}else text(section,'p','尚无授权信息。');
 if(p.reason==='authorization_pending')text(section,'p','浏览器收起后可用“展开 / 重新进入浏览器”恢复原窗口。');
 section=detail(content,'环境保护与备份');text(section,'p',protectionLabels[protection.phase]||'环境保护状态未知');if(protection.environment_id)text(section,'p','环境编号：'+protection.environment_id.slice(0,12));if(protection.initial_backup)text(section,'p','初始环境备份：已完成');if(protection.verified_at)text(section,'p','完整备份校验：'+new Date(protection.verified_at*1000).toLocaleString());
 if(backup){text(section,'p',backup.state==='exported'?'加密备份已保存 · 凭据版本 '+backup.revision+' · '+new Date(backup.exported_at*1000).toLocaleString():backup.state==='not_created'?'创建环境后自动备份':backup.state==='not_exported'?'等待保存加密备份包':'备份位置暂不可用');if(backup.warning)text(section,'p','最近一次备份未完成，已有备份保留，可重试。');}text(section,'p','本地备份不能覆盖整台主机丢失；异机副本尚未验证。');
 section=detail(content,'上游额度观测');for(const line of quotaLines(p.state?.quota_observation))text(section,'p',line);
 section=detail(content,'已确认用量');if(p.usage){const u=p.usage;text(section,'p','输入：'+(u.totals.input_tokens??'未报告')+' · 输出：'+(u.totals.output_tokens??'未报告'));text(section,'p','完整 '+u.attempt_counts.confirmed+' · 部分 '+u.attempt_counts.partial+' · 未报告 '+u.attempt_counts.unreported+' · 异常 '+u.attempt_counts.invalid);text(section,'p','模型报告值，不是账单；部分记录不计入合计。');}else text(section,'p','暂无用量记录。');
 section=detail(content,'最近执行记录');if(!p.attempts?.length)text(section,'p','暂无执行记录。');for(const a of p.attempts||[])text(section,'p',(results[a.state]||a.state)+' · '+a.id.slice(0,10)+(a.status?' · HTTP '+a.status:'')+(a.stop_reason?' · '+(stops[a.stop_reason]||a.stop_reason):''));
 const more=text(content,'div','','detail-actions');if(p.state?.authorized&&!p.state.refreshing)action(more,'auth-refresh','立即刷新凭据',true);if(protection.backup_verified)action(more,'backup-export','更新加密备份',true);if(['container_stopped','worker_unavailable','network_status_unknown','binding_check_failed'].includes(p.reason)&&backup?.state==='exported')action(more,'backup-restore','从加密备份恢复',true);if(!more.children.length)more.hidden=true;
}

async function refresh(force=false){if(busy||(!force&&['INPUT','SELECT'].includes(document.activeElement?.tagName)))return;busy=true;const focusKey=document.activeElement?.dataset?.focusId;try{
 const token=sessionStorage.getItem(tokenKey);if(!token)throw Error('请返回管理首页登录。');
 const r=await fetch('/snapshot',{headers:{'X-Offline-View':token},cache:'no-store'});if(!r.ok)throw Error(r.status===401?'管理登录失效，请重新登录。':'状态读取失败；旧状态不能作为派单依据。');
 const data=await r.json();
 const providerSelect=document.querySelector('#account-provider');const oldProvider=providerSelect.value;providerSelect.replaceChildren();
 for(const [value,info] of Object.entries(data.providers||{})){const option=text(providerSelect,'option',info.label);option.value=value;}
 if([...providerSelect.options].some(o=>o.value===oldProvider))providerSelect.value=oldProvider;providerSelect.disabled=providerSelect.options.length===0;
 document.querySelector('#runtime-mode').textContent=data.runtime_mode==='managed'?'运行模式：账号独立容器 · 真实订阅通道待验收':data.runtime_mode==='closed_tls_test'?'闭网 HTTPS 测试 · 官方域名由本地测试服务响应 · 没有真实账号':'闭网模拟测试 · 没有真实账号';
 if(trackedAuthorization&&!working){const current=data.projects.find(p=>p.slug===trackedAuthorization);if(current){const phase=current.protection?.phase;const progress=document.querySelector('#progress');if(phase==='ready'){progress.textContent='授权已保存，浏览器已关闭，环境备份校验通过。实际接单资格请看账号卡片。';delete viewers[trackedAuthorization];trackedAuthorization='';}else if(phase==='authorizing'){progress.textContent='正在等待容器浏览器内的授权操作；完成后自动关闭浏览器并备份。';}else if(phase){progress.textContent=protectionLabels[phase]||'正在检查授权后的环境状态。';}}}
 renderLogging(data.logging_to_file);
 accounts.replaceChildren();document.querySelector('#version').textContent='运行版本：'+data.release.candidate+' · 自动刷新并发：'+(data.refresh_workers??'未知');
 currentProjects=data.projects;
 document.querySelector('#count-all').textContent=data.projects.length;
 document.querySelector('#count-ready').textContent=data.projects.filter(p=>p.overall_ready).length;
 document.querySelector('#count-pending').textContent=data.projects.filter(p=>!p.overall_ready).length;
 document.querySelector('#list-count').textContent=data.projects.length?String(data.projects.length):'';
 if(!data.projects.length){
  const empty=text(accounts,'div','','empty');
  empty.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="7" rx="2"/><rect x="3" y="14" width="18" height="7" rx="2"/><path d="M7 6.5h.01M7 17.5h.01M12 6.5h5M12 17.5h5"/></svg>';
  text(empty,'h3','添加你的第一个账号');text(empty,'p','每个账号拥有独立容器。绑定代理并完成浏览器授权后，在这里查看接单状态。');
  const steps=text(empty,'div','','onboarding');for(const [index,label] of ['绑定代理','浏览器授权','环境就绪'].entries()){const step=text(steps,'span','');text(step,'b',index+1);text(step,'span',label);}
  const button=text(empty,'button','添加账号');button.onclick=()=>showAdd();
 }
 for(const p of data.projects)renderCard(p,data);
 const noMatch=text(accounts,'p','没有匹配的账号，请尝试其他名称或编号。','empty');noMatch.id='search-empty';noMatch.hidden=true;filterAccounts();
 const requestList=document.querySelector('#requests');requestList.replaceChildren();
 if(!data.requests.length)text(requestList,'p','尚无请求记录。账号开始接单后，可在这里核对每次请求的执行路径。');
 for(const group of data.requests){const block=text(requestList,'article','');text(block,'h3','请求 '+group.run);
 group.attempts.forEach((a,i)=>{text(block,'p','第 '+(i+1)+' 次 · 账号 '+a.owner+' · '+(results[a.state]||a.state)+(a.status?' · HTTP '+a.status:'')+' · 容器 '+(a.container?a.container.slice(0,12):'未派入'));
 if(a.response)text(block,'p','回复摘要：'+a.response.slice(0,16)+'…');});
 if(group.truncated)text(block,'p','记录超过页面上限，需查询完整本地记录。');}
 status.className='';status.textContent='更新于 '+new Date().toLocaleTimeString();
 }catch(e){renderLogging(null);status.textContent=e.message;status.className='error';for(const id of ['count-all','count-ready','count-pending'])document.querySelector('#'+id).textContent='—';accounts.replaceChildren();const failure=text(accounts,'div','','empty');text(failure,'h3','暂时无法读取账号状态');text(failure,'p','请检查管理服务连接后重试。当前页面不显示过期的接单状态。');const retry=text(failure,'button','重新读取');retry.onclick=()=>refresh(true);document.querySelector('#requests').replaceChildren();}finally{busy=false;if(focusKey){[...accounts.querySelectorAll('[data-focus-id]')].find(el=>el.dataset.focusId===focusKey)?.focus({preventScroll:true});}}}
document.querySelector('#refresh').addEventListener('click',()=>refresh(true));refresh();setInterval(()=>{if(!document.hidden)refresh();},5000);

async function operate(slug,action){
 if(working)return;working=true;const progress=document.querySelector('#progress');
 const messages={'backup-export':'已请求更新加密备份，执行器继续运行…','backup-restore':'正在验证备份并恢复到新数据卷，保留原数据…','retry-backup':'正在使用已保存的授权重新备份和校验，不重新登录…',create:'正在校验代理配置、准备容器并检查网络…','auth-begin':'正在启动容器浏览器和授权回调…','open-browser':'正在恢复窗口并连接原来的容器浏览器…','close-browser':'正在关闭容器浏览器…','auth-complete':'正在保存凭据、关闭浏览器并校验完整环境备份…','auth-cancel':'正在取消授权…','auth-refresh':'正在立即刷新凭据；有效访问凭据仍可接单…',restart:'正在重启并核对持久状态…'};
 progress.textContent=messages[action];document.querySelectorAll('article button').forEach(b=>b.disabled=true);
 if(action==='create'){const card=[...accounts.querySelectorAll('.account-card')].find(c=>c.dataset.account===slug);if(card)text(card.querySelector('.card-main'),'p','正在提交创建请求…','creation-submitting').setAttribute('role','status');}
 try{const body={slug,action};if(action==='create')body.proxy_url=proxies[slug];if(action==='auth-complete')body.state=pending[slug];
 const r=await fetch('/action',{method:'POST',headers:{'Content-Type':'application/json','X-Offline-View':sessionStorage.getItem(tokenKey)},body:JSON.stringify(body)});const data=await r.json();
 if(!r.ok){const code=data.error?.message||data.error;throw Error(labels[code]||'刷新或操作未完成，请查看账号的服务状态与刷新状态。');}
 if(data.viewer_url){viewers[slug]=data.viewer_url;trackedAuthorization=slug;}
 if(action==='create')delete proxies[slug];
 if(action==='auth-complete'||action==='auth-cancel')delete pending[slug];
 progress.textContent=data.queued?'加密备份已排队，稍后自动更新结果；不额外停止调用。':data.viewer_url?'浏览器已启动，请点击账号卡片里的「进入容器浏览器」。授权后会自动关闭浏览器、备份并检查派单条件。':'操作已完成，账号状态已更新。';
 }catch(e){progress.textContent=e.message;}finally{working=false;await refresh(true);}
}

const accountForm=document.querySelector('#account-form');
accountForm.addEventListener('submit',async event=>{
 event.preventDefault();if(working)return;working=true;
 const feedback=document.querySelector('#account-feedback'),submit=document.querySelector('#account-submit');submit.disabled=true;feedback.className='';feedback.textContent='正在保存账号记录…';
 try{
  const body={action:'register',slug:document.querySelector('#account-id').value,label:document.querySelector('#account-label').value,provider:document.querySelector('#account-provider').value};
  const response=await fetch('/action',{method:'POST',headers:{'Content-Type':'application/json','X-Offline-View':sessionStorage.getItem(tokenKey)},body:JSON.stringify(body)});
  const value=await response.json();if(!response.ok)throw Error(labels[value.error?.message||value.error]||'账号未保存，请检查配置后重试。');
  accountForm.reset();trackedAuthorization='';showAdd(false);document.querySelector('#progress').textContent='账号已保存，请填写 SOCKS 地址并创建环境。';feedback.textContent='账号已保存。请在下方账号卡片中填写 SOCKS，继续创建环境。';
 }catch(error){feedback.className='error';feedback.textContent=error.message;}
 finally{working=false;submit.disabled=false;await refresh(true);}
});

  }
  session.subscribe((next, before) => {
    if (next.isAuthenticated !== before.isAuthenticated || next.apiBase !== before.apiBase || next.managementKey !== before.managementKey) sync();
  });
  let wasAccountPage = isAccountPage();
  addEventListener('popstate', () => {
    const now = isAccountPage();
    if (wasAccountPage !== now) { wasAccountPage = now; sync(); }
  });
  sync();
})(dh, Zc);

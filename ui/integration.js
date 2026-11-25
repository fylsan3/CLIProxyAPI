(function accountConsole(session, theme) {
  'use strict';
  const nativeDocument = document;
  const host = nativeDocument.createElement('div');
  host.id = 'account-environments-app';
  host.dataset.uiRevision = 'accounts-ui1';
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
    root.innerHTML = '<style>__CSS__</style>';
    const page = nativeDocument.createElement('section');
    page.innerHTML = __MARKUP__;
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
    __QUOTA__
    __SETTINGS__
    __APP__
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

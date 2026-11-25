'use strict';
const tokenKey='native-refresh-view';const pending={};const proxies={};const revealedProxies={};const viewers={};let trackedAuthorization='';let working=false;let confirming=false;
if(location.hash.length>1){sessionStorage.setItem(tokenKey,location.hash.slice(1));history.replaceState(null,'',location.pathname);}
const labels={authorization_url_rejected:'浏览器入口地址校验失败，请检查授权入口',browser_restore_unavailable:'窗口恢复失败，请关闭浏览器后重新打开',browser_operation_failed:'容器浏览器操作失败，请检查容器状态',account_busy:'该账号仍有任务或凭据刷新进行中，请等待结束后重启',account_maintenance:'账号正在重启检查，暂不接新任务',container_unavailable:'容器未运行，请先启动容器',account_ready:'可接单',invalid_account_id:"账号编号格式有误，请使用小写英文字母、数字和中划线，末尾不能为中划线",invalid_account_label:"显示名称须为 1—60 个字符，不能含首尾空格或控制字符",provider_not_available:"当前运行配置不支持该提供方，请检查配置",account_already_registered:"该编号已绑定其他账号记录，请使用新的编号",account_not_registered:"未找到账号记录，请先添加账号",browser_sandbox_unavailable:"浏览器安全隔离检查未通过，窗口已关闭；请检查容器安全规则",browser_start_failed:"容器浏览器启动失败，请检查浏览器运行环境",stop_account_before_restore:"请先停止该账号容器再恢复，当前数据不会被覆盖",backup_card_changed:"备份不属于当前账号环境，已拒绝恢复",backup_package_changed:"备份文件发生变化，已拒绝恢复",backup_credentials_older_than_local:"备份凭据比本地旧，已拒绝覆盖",backup_restore_failed:"备份校验或恢复未完成，原账号数据已保留",account_proxy_unavailable:"账号代理或出口检查失败，已停派",network_status_unknown:"网络检查状态无法确认，已停派",environment_backup_required:'环境备份未通过，暂不派单',environment_protection_unknown:'环境保护状态无法确认，暂不派单',missing:'尚未创建',container_stopped:'容器已停止',worker_unavailable:'执行器不可用',binding_check_failed:'容器或数据盘归属检查失败',credential_save_failed:'凭据保存失败',offline_ready:'离线测试可接单',authorization_pending:'正在等待授权',authorization_required:'需要授权',credential_expired:'访问凭据已到期，已停派',credential_rejected:'访问凭据被拒，已停派',account_disabled:'账号已停用',account_unavailable:'账号不可用或冷却中'};
Object.assign(labels,creationErrors);
const protectionLabels={not_created:'尚未创建',creating:'正在准备账号环境与初始备份',creation_failed:'创建未完成，需要检查环境',awaiting_authorization:'初始环境备份完成，等待授权',authorizing:'正在等待授权',exchanging_credentials:'正在保存授权凭据',authorization_failed:'授权未完成',closing_browser:'正在关闭浏览器',saving_backup:'正在保存授权后环境',verifying_backup:'正在校验完整备份',starting_protected_environment:'正在恢复执行器',ready:'环境与备份校验通过',backup_failed:'备份未完成，可重试，不需要重新授权',checking_restore:'正在检查恢复条件',recovery_check_failed:'恢复检查未通过，已停派'};
const authorizationLabels={authorization_cancelled:'已取消授权',authorization_expired:'授权等待已超时',authorization_denied:'已在授权页面取消',authorization_exchange_failed:'授权信息交换未完成'};
const renewalLabels={sign_in_required:'续期需要登录；服务状态单独判断',expired_sign_in_required:'凭据不可用，需要登录',retry_scheduled:'刷新失败，已安排重试',renewal_verified:'最近刷新成功',awaiting_first_renewal:'尚未刷新'};
const results={preparing:'正在检查执行条件',not_dispatched:'未派入容器',running:'执行中',completed:'执行已完成',result_unknown:'执行结果待确认'};
const stops={environment_backup_required:"环境备份未通过，未派入容器",environment_protection_unknown:"环境保护状态无法确认，未派入容器",client_disconnected:'客户端已断开，已请求停止',controller_stopping:'控制服务正在停止',execution_interrupted:'执行链路中断',client_delivery_incomplete:'执行已完成，客户端接收不完整'};
const status=document.querySelector('#status'),accounts=document.querySelector('#accounts');let busy=false;
function text(parent,tag,value,className){const e=document.createElement(tag);e.textContent=value;if(className)e.className=className;parent.append(e);return e;}
function detail(parent,title){const section=text(parent,'section','');text(section,'h3',title);return section;}
function fact(parent,label,value,tone=''){const group=text(parent,'div','');text(group,'dt',label);text(group,'dd',value,tone);}
const failedReasons=new Set(['container_stopped','worker_unavailable','binding_check_failed','credential_save_failed','account_proxy_unavailable','network_status_unknown','environment_backup_required','environment_protection_unknown','credential_expired','credential_rejected','account_disabled','account_unavailable']);
const failedPhases=new Set(['creation_failed','authorization_failed','backup_failed','recovery_check_failed']);
function accountTone(p){return p.overall_ready?'status-ok':failedPhases.has(p.protection?.phase)||failedReasons.has(p.reason)||p.state?.authorization_issue?'status-bad':'';}
function attemptTone(a){return a.stop_reason||Number(a.status)>=400||a.state==='not_dispatched'?'status-bad':a.state==='completed'&&Number(a.status)>=200&&Number(a.status)<300?'status-ok':'';}

function showAdd(open=true){const panel=document.querySelector('#account-add');panel.hidden=!open;document.querySelector('#add-account').setAttribute('aria-expanded',String(open));if(open)document.querySelector('#account-proxy').focus();else document.querySelector('#add-account').focus();}
// Local presentation only: no account action or request payload is changed.
const cardMotion=(()=>{
 const reduced=matchMedia('(prefers-reduced-motion: reduce)'),fine=matchMedia('(hover: hover) and (pointer: fine)');
 const records=new Map();
 const visible=new IntersectionObserver(entries=>entries.forEach(e=>e.target.classList.toggle('motion-visible',e.isIntersecting)),{threshold:0});
 function reset(card){const r=records.get(card);if(r?.frame)cancelAnimationFrame(r.frame);if(r)r.frame=0;card.classList.remove('pointer-lit');card.style.setProperty('--tilt-x','0deg');card.style.setProperty('--tilt-y','0deg');}
 function finish(card){const r=records.get(card);if(!r?.animations)return;r.animations.forEach(a=>a.finish());r.complete?.();}
 function bind(card){const r={frame:0};records.set(card,r);visible.observe(card);
  card.addEventListener('pointermove',e=>{if(!fine.matches||reduced.matches||e.pointerType==='touch'||r.animations||r.portal)return;const x=e.clientX,y=e.clientY;if(r.frame)cancelAnimationFrame(r.frame);r.frame=requestAnimationFrame(()=>{r.frame=0;const box=card.getBoundingClientRect();const px=Math.max(0,Math.min(1,(x-box.left)/box.width)),py=Math.max(0,Math.min(1,(y-box.top)/box.height));let tx=(.5-py)*8,ty=(px-.5)*8;const scale=Math.max(1,Math.hypot(tx,ty)/4);card.style.setProperty('--light-x',px*100+'%');card.style.setProperty('--light-y',py*100+'%');card.style.setProperty('--tilt-x',tx/scale+'deg');card.style.setProperty('--tilt-y',ty/scale+'deg');card.classList.add('pointer-lit');});});
  card.addEventListener('pointerleave',()=>reset(card));card.addEventListener('pointercancel',()=>reset(card));
 }
 function expand(card,shell,content,open){finish(card);reset(card);const r=records.get(card);if(!r)return;
  if(open){
   if(r.portal)return;
   const origin=card.getBoundingClientRect(),slot=document.createElement('div');slot.className='account-slot';slot.dataset.account=card.dataset.account;slot.dataset.search=card.dataset.search;slot.style.height=origin.height+'px';slot.setAttribute('aria-hidden','true');card.before(slot);
   const portal=document.createElement('dialog');portal.className='detail-portal';portal.setAttribute('aria-label',(card.querySelector('h2')?.textContent||'账号')+' · 详情');accounts.parentElement.append(portal);r.portal=portal;r.slot=slot;
   portal.append(card);content.hidden=false;card.classList.add('is-expanded');portal.showModal();
   const close=()=>card.querySelector('.detail-toggle')?.click();portal.addEventListener('cancel',e=>{e.preventDefault();close();});portal.addEventListener('click',e=>{if(e.target===portal){const b=card.getBoundingClientRect();if(e.clientX<b.left||e.clientX>b.right||e.clientY<b.top||e.clientY>b.bottom)close();}});
   const dest=card.getBoundingClientRect();const from=`translate(${origin.left-dest.left}px,${origin.top-dest.top}px) scale(${origin.width/dest.width},${origin.height/dest.height})`;
   animate(card,r,from,'none',true,()=>{card.querySelector('.detail-toggle')?.focus({preventScroll:true});});
  }else if(r.portal){
   const current=card.getBoundingClientRect(),dest=r.slot.getBoundingClientRect();const to=`translate(${dest.left-current.left}px,${dest.top-current.top}px) scale(${dest.width/current.width},${dest.height/current.height})`;
   animate(card,r,'none',to,false,()=>{const portal=r.portal;r.slot.before(card);r.slot.remove();r.slot=null;r.portal=null;portal.close();portal.remove();content.hidden=true;shell.hidden=true;card.classList.remove('is-expanded');card.querySelector('.detail-toggle')?.focus({preventScroll:true});});
  }else{content.hidden=true;shell.hidden=true;card.classList.remove('is-expanded');}
 }
 function animate(card,r,from,to,open,done){
  const complete=()=>{if(r.complete!==complete)return;r.animations?.forEach(a=>a.cancel());r.animations=null;r.complete=null;card.classList.remove('detail-moving');done();};r.complete=complete;
  if(reduced.matches){complete();return;}card.classList.add('detail-moving');
  r.animations=[card.animate([{transform:from},{transform:to}],{duration:open?380:280,easing:'cubic-bezier(.22,.8,.2,1)',fill:'both'})];Promise.all(r.animations.map(a=>a.finished.catch(()=>{}))).then(complete);
 }
 function remove(card){finish(card);reset(card);const r=records.get(card);if(r?.portal){r.portal.close();r.portal.remove();r.slot?.remove();}visible.unobserve(card);records.delete(card);}
 const owner=accounts.ownerDocument;function visibility(){accounts.classList.toggle('motion-paused',owner.hidden);if(owner.hidden)records.forEach((_,c)=>reset(c));}
 owner.addEventListener('visibilitychange',visibility);const onReduce=()=>records.forEach((_,c)=>{reset(c);finish(c);});reduced.addEventListener('change',onReduce);window.addEventListener('blur',onReduce);
 const cleanup=()=>{records.forEach((_,c)=>remove(c));visible.disconnect();owner.removeEventListener('visibilitychange',visibility);reduced.removeEventListener('change',onReduce);window.removeEventListener('blur',onReduce);};
 if(typeof controller!=='undefined')controller.signal.addEventListener('abort',cleanup,{once:true});
 return {bind,expand,finish,remove};
})();

const expandedAccounts=new Set();let currentProjects=[];
function filterAccounts(){const q=document.querySelector('#account-search').value.trim().toLocaleLowerCase();let shown=0;for(const card of accounts.querySelectorAll('.account-card,.account-slot')){card.hidden=!card.dataset.search.includes(q);if(!card.hidden)shown++;}const empty=document.querySelector('#search-empty');if(empty)empty.hidden=!currentProjects.length||shown>0;}
document.querySelector('#add-account').onclick=()=>showAdd();document.querySelector('#cancel-add').onclick=()=>showAdd(false);document.querySelector('#account-search').addEventListener('input',filterAccounts);
function renderCard(p,data){
 let card=[...document.querySelectorAll('.account-card')].find(c=>c.dataset.account===p.slug);
 const detailScroll=card?.querySelector('.account-detail')?.scrollTop||0;
 if(!card){card=text(accounts,'article','','account-card');card.dataset.account=p.slug;cardMotion.bind(card);}else{cardMotion.finish(card);for(const child of [...card.children])if(!child.classList.contains('border-beam'))child.remove();}
 card.classList.toggle('has-issue',accountTone(p)==='status-bad'||p.network?.healthy===false||!!p.network?.timezone_warning||!!p.state?.storage_warning||!!p.portable_backup?.warning);
 const beam=card.querySelector('.border-beam')||text(card,'span','','border-beam');beam.setAttribute('aria-hidden','true');
 card.dataset.search=((p.label||'')+' '+p.slug).toLocaleLowerCase();
 const main=text(card,'div','','card-main'),heading=text(main,'div','','card-heading'),title=text(heading,'div','','account-title');
 text(title,'h2',p.identity?.email||p.label||'待授权账号');text(title,'span',subscriptionLabel(p.state),'subscription-badge');text(title,'p',data.providers?.[p.provider]?.label||p.provider,'muted');
 const needsAuth=['authorization_required','authorization_pending'].includes(p.reason);
 const headingActions=text(heading,'div','','card-heading-actions');
 text(headingActions,'span',p.overall_ready?'可接单':p.protection?.phase==='creating'?'创建中':p.protection?.phase==='creation_failed'?'创建失败':p.reason==='missing'?'待创建环境':p.reason==='authorization_pending'?'等待授权':p.reason==='authorization_required'?'需要授权':'暂停接单','badge '+accountTone(p));
 const protection=p.protection||{phase:'not_created'},backup=p.portable_backup,central=p.central_dispatch||{reason:'unknown'};
 const centralLabels={eligible:'调度条件满足',cooldown:'中央冷却中',disabled:'中央已停用',unavailable:'中央暂不可用',unknown:'中央状态无法读取'};
 const facts=text(main,'dl','','card-facts');fact(facts,'容器状态',p.protection?.phase==='creating'?'正在准备环境':p.protection?.phase==='creation_failed'?'创建未完成':p.reason==='missing'?'尚未创建':labels[p.reason]||'状态待确认',accountTone(p));fact(facts,'账号网络',p.network?(p.network.healthy?'检查通过':'检查未通过'): '等待检查',p.network?(p.network.healthy?'status-ok':'status-bad'):'');fact(facts,'活动请求',p.state?.active_calls??'—');
 const notice=protection.phase==='creating'?'正在准备此账号的独立运行环境，请查看下方进度。':protection.phase==='creation_failed'?'创建未完成，请查看下方失败步骤与原因。':p.reason==='missing'?'绑定 SOCKS 后创建此账号的独立运行环境。':needsAuth?'在容器浏览器内完成授权，完成后自动关闭浏览器并保存环境。':!p.overall_ready?(labels[p.reason]||centralLabels[central.reason]||'请展开详情查看原因。'):'';
 text(main,'p',notice,'card-notice '+(accountTone(p)==='status-bad'?'status-bad':''));
 if(p.network?.timezone_warning)text(main,'p',p.network.timezone_check_reason==='timezone_changed'?'出口时区与固定时区不同；继续使用 '+p.network.fixed_timezone+'。':'本次未能核对出口时区；继续使用已保存的时区。','card-notice status-bad');
 if(p.state?.authorization_issue)text(main,'p',authorizationLabels[p.state.authorization_issue]||'授权未完成，请查看详情。','error');
 if(p.state?.storage_warning)text(main,'p','凭据保存或备份异常，请检查存储；有效调用继续按 CPA 原逻辑处理。','error');
 renderCreation(main,p);
 renderAccountQuota(main,p);
 const actions=text(main,'div','','actions');
 if(p.reason==='missing'&&['not_created','creation_failed'].includes(protection.phase)){
  const label=text(main,'label','账号 SOCKS 地址','proxy-entry'),input=document.createElement('input');input.type='text';input.spellcheck=false;input.autocomplete='off';input.placeholder='socks5h://用户名:密码@IP:端口';input.value=proxies[p.slug]||'';input.dataset.owner=p.slug;input.addEventListener('input',()=>proxies[p.slug]=input.value);label.append(input);main.append(actions);
 }
 function action(parent,operation,label,secondary=false){const b=text(parent,'button',label,secondary?'secondary':'');b.dataset.focusId=p.slug+':'+operation;b.disabled=working;b.addEventListener('click',()=>operate(p.slug,operation));return b;}
 if(p.reason==='missing'&&['not_created','creation_failed'].includes(protection.phase))action(actions,'create','校验代理并创建容器');
 if(p.state?.authorized){const b=action(actions,'account-update',p.state.account_updating?'正在更新…':'更新账号资料',true);b.disabled=working||p.state.account_updating;}
 if(p.reason==='authorization_required')action(actions,'auth-begin','打开浏览器授权');
 if(p.container){
  if(viewers[p.slug]){const link=text(actions,'a','进入容器浏览器','button-link');link.href=viewers[p.slug];link.target='_blank';link.rel='noreferrer noopener';}
  const stopped=p.reason==='container_stopped';
  if(!stopped){action(actions,'open-browser',viewers[p.slug]?'展开 / 重新进入浏览器':'打开容器浏览器',true);if(viewers[p.slug])action(actions,'close-browser','关闭容器浏览器',true);}
  if(p.reason==='authorization_pending')action(actions,'auth-cancel','取消本次授权',true);
  const restart=action(actions,'restart',stopped?'启动容器':'重启容器',true);
  if((p.state?.active_calls||0)>0||p.state?.refreshing||p.reason==='authorization_pending'||p.reason==='account_maintenance'){restart.disabled=true;restart.title='请等待正在执行的任务、刷新或授权完成后再重启';}
 }
 if(['backup_failed','recovery_check_failed'].includes(protection.phase)||(p.state?.authorized&&!protection.backup_verified))action(actions,'retry-backup','重试环境备份');
 if(!actions.children.length)actions.hidden=true;
 const details=text(card,'section','','account-detail');
 const toggle=text(headingActions,'button',expandedAccounts.has(p.slug)?'关闭详情':'详情','detail-toggle secondary');
 toggle.dataset.focusId=p.slug+':details';toggle.setAttribute('aria-expanded',String(expandedAccounts.has(p.slug)));toggle.setAttribute('aria-controls','details-'+p.slug);toggle.setAttribute('aria-label',(p.label||p.slug)+' · '+(expandedAccounts.has(p.slug)?'关闭详情':'详情'));
 details.hidden=!expandedAccounts.has(p.slug);
 const content=text(details,'div','','detail-content');content.id='details-'+p.slug;content.hidden=!expandedAccounts.has(p.slug);card.classList.toggle('is-expanded',!content.hidden);
 function showDetails(open){details.hidden=false;if(open)expandedAccounts.add(p.slug);else expandedAccounts.delete(p.slug);toggle.textContent=open?'关闭详情':'详情';toggle.setAttribute('aria-label',(p.label||p.slug)+' · '+toggle.textContent);toggle.setAttribute('aria-expanded',String(open));cardMotion.expand(card,details,content,open);}
 toggle.onclick=()=>showDetails(!expandedAccounts.has(p.slug));card.onkeydown=e=>{if(e.key==='Escape'&&expandedAccounts.has(p.slug)){e.preventDefault();showDetails(false);toggle.focus({preventScroll:true});}};
 let section=detail(content,'环境与网络');
 text(section,'p','容器编号：'+(p.container?p.container.slice(0,12):'未创建'));text(section,'p','中央调度：'+(centralLabels[central.reason]||'未知'),central.reason==='eligible'?'status-ok':'status-bad');
 if(p.container){
  if(revealedProxies[p.slug]){const label=text(section,'label','已绑定的 SOCKS 地址','proxy-entry'),input=document.createElement('input');input.type='text';input.readOnly=true;input.value=revealedProxies[p.slug];input.autocomplete='off';input.spellcheck=false;label.append(input);const hide=text(section,'button','收起 SOCKS 地址','secondary');hide.onclick=()=>{delete revealedProxies[p.slug];refresh(true);};}
  else action(section,'proxy-view','查看 SOCKS 地址（明文）',true);
 }
 if(central.retry_after)text(section,'p','下次可重试：'+new Date(central.retry_after).toLocaleString());
 if(p.network){text(section,'p',p.network.healthy?'启动网络检查通过；不进行定时公网出口探测。':'网络检查未通过或本地监督失联，已暂停新任务。',p.network.healthy?'status-ok':'status-bad');if(p.network.fixed_timezone)text(section,'p','固定时区：'+p.network.fixed_timezone+' · 系统与浏览器语言：英语');if(p.network.observed_timezone&&p.network.timezone_warning)text(section,'p','本次出口时区：'+p.network.observed_timezone,'status-bad');if(p.network.network_checked_at)text(section,'p','启动检查：'+new Date(p.network.network_checked_at*1000).toLocaleString());if(p.network.last_success_at)text(section,'p','最近检查成功：'+new Date(p.network.last_success_at*1000).toLocaleString());if(p.network.checking)text(section,'p','正在检查代理和公网出口…');}
 if(p.exit_code!==undefined)text(section,'p','容器退出码：'+p.exit_code,p.exit_code===0?'':'status-bad');
 section=detail(content,'授权与凭据');
 const subscription=p.state?.subscription;
 text(section,'p','订阅档位：'+subscriptionLabel(p.state));
 if(p.state?.account_email_masked)text(section,'p','账号邮箱：'+p.state.account_email_masked);
 if(!p.state?.last_refresh)text(section,'p','最近成功刷新：尚无保存记录');
 if(!p.state?.next_refresh)text(section,'p','下次刷新：沿用 CPA 到期检查与失败重试机制，尚无固定时间');
 if(p.state){text(section,'p','凭据修订：'+p.state.revision);text(section,'p','刷新：'+(p.state.refreshing?'正在刷新，有效凭据继续服务':renewalLabels[p.state.renewal_state]||'空闲'),['sign_in_required','expired_sign_in_required','retry_scheduled'].includes(p.state.renewal_state)?'status-bad':p.state.refreshing?'':p.state.authorized?'status-ok':'');for(const [key,label] of [['expires','访问令牌到期（不是订阅到期）'],['last_refresh','最近刷新'],['next_refresh','最早下次检查']])if(p.state[key])text(section,'p',label+'：'+new Date(p.state[key]).toLocaleString(),key==='expires'&&Number.isFinite(Date.parse(p.state[key]))&&Date.parse(p.state[key])<=Date.now()?'status-bad':'');}else text(section,'p','尚无授权信息。');
 if(p.container)text(section,'p','打开浏览器会进入此账号原有环境，不会自动发起新的授权。关闭网页标签只是收起窗口；“关闭容器浏览器”才会停止浏览器。');
 if(p.last_success_at)text(section,'p','最近成功调用：'+new Date(p.last_success_at*1000).toLocaleString(),'status-ok');else text(section,'p','尚无成功调用记录；可接单表示本地条件通过。');
 section=detail(content,'环境保护与备份');text(section,'p',protectionLabels[protection.phase]||'环境保护状态未知',protection.phase==='ready'?'status-ok':failedPhases.has(protection.phase)?'status-bad':'');if(protection.environment_id)text(section,'p','环境编号：'+protection.environment_id.slice(0,12));if(protection.initial_backup)text(section,'p','初始环境备份：已完成','status-ok');if(protection.verified_at)text(section,'p','完整备份校验：'+new Date(protection.verified_at*1000).toLocaleString(),'status-ok');
 if(backup){text(section,'p',backup.state==='exported'?'加密备份已保存 · 凭据版本 '+backup.revision+' · '+new Date(backup.exported_at*1000).toLocaleString():backup.state==='not_created'?'创建环境后自动备份':backup.state==='not_exported'?'等待保存加密备份包':'备份位置暂不可用',backup.state==='exported'?'status-ok':['not_created','not_exported'].includes(backup.state)?'':'status-bad');if(backup.stale)text(section,'p','加密包为旧凭据版本，当前版本 '+backup.current_revision+'；正在等待自动导出更新。','status-bad');if(backup.environment_outdated)text(section,'p','加密包尚未更新到当前运行环境；已保留旧包，等待导出完成。','status-bad');if(backup.warning&&!backup.stale&&!backup.environment_outdated)text(section,'p',backup.state==='exported'?'最近一次加密导出未完成，上一份加密包保留，可重试。':'加密备份包尚未生成；容器内完整备份仍保留，请重试导出。','status-bad');if(backup.error_code)text(section,'p',({backup_too_large:'压缩后的加密包超过大小上限',backup_expanded_too_large:'备份内容超过解压大小上限',checkpoint_changed_retry_export:'备份期间凭据更新，请重新导出',backup_export_failed:'导出未完成，请检查存储空间与备份记录'})[backup.error_code]||'导出错误待检查','status-bad');}text(section,'p','本地备份不能覆盖整台主机丢失；异机副本尚未验证。');
 section=detail(content,'上游额度观测');renderAccountQuota(section,p);if(p.state?.quota_observation?.reported)for(const line of quotaLines(p.state.quota_observation))text(section,'p',line);
 section=detail(content,'已确认用量');if(p.usage){const u=p.usage;text(section,'p','输入：'+(u.totals.input_tokens??'未报告')+' · 输出：'+(u.totals.output_tokens??'未报告'));const counts=text(section,'p','');for(const [key,label] of [['confirmed','完整'],['partial','部分'],['unreported','未报告'],['invalid','异常']]){if(counts.childNodes.length)text(counts,'span',' · ');const n=u.attempt_counts[key];text(counts,'span',label+' '+n,n>0?(key==='confirmed'?'status-ok':key==='invalid'?'status-bad':''):'');}text(section,'p','模型报告值，不是账单；部分记录不计入合计。');}else text(section,'p','暂无用量记录。');
 section=detail(content,'累计请求');if(p.statistics)text(section,'p','请求 '+p.statistics.requests+' · 执行尝试 '+p.statistics.attempts+' · 成功 '+p.statistics.successful_attempts+' · 失败 '+p.statistics.failed_attempts);
 section=detail(content,'最近执行记录');if(!p.attempts?.length)text(section,'p','暂无执行记录。');for(const a of p.attempts||[])text(section,'p',(results[a.state]||a.state)+' · '+a.id.slice(0,10)+(a.status?' · HTTP '+a.status:'')+(a.stop_reason?' · '+(stops[a.stop_reason]||a.stop_reason):''),attemptTone(a));
 const more=text(content,'div','','detail-actions');if(p.state?.authorized&&!p.state.refreshing)action(more,'auth-refresh','立即刷新凭据',true);if(protection.backup_verified)action(more,'backup-export','更新加密备份',true);if(['container_stopped','worker_unavailable','network_status_unknown','binding_check_failed'].includes(p.reason)&&backup?.state==='exported')action(more,'backup-restore','从加密备份恢复',true);if(!more.children.length)more.hidden=true;details.scrollTop=detailScroll;
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
 for(const card of document.querySelectorAll('.account-card'))if(!data.projects.some(p=>p.slug===card.dataset.account)){cardMotion.remove(card);card.remove();}
 for(const child of [...accounts.children])if(!child.matches('.account-card,.account-slot'))child.remove();
 document.querySelector('#version').textContent='运行版本：'+data.release.candidate+' · 自动刷新并发：'+(data.refresh_workers??'未知');
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
 const noMatch=text(accounts,'p','没有匹配的账号，请尝试其他邮箱。','empty');noMatch.id='search-empty';noMatch.hidden=true;filterAccounts();
 const requestList=document.querySelector('#requests');requestList.replaceChildren();
 if(!data.requests.length)text(requestList,'p','尚无请求记录。账号开始接单后，可在这里核对每次请求的执行路径。');
 for(const group of data.requests){const block=text(requestList,'article','');text(block,'h3','请求 '+group.run);
 group.attempts.forEach((a,i)=>{text(block,'p','第 '+(i+1)+' 次 · 账号 '+a.owner+' · '+(results[a.state]||a.state)+(a.status?' · HTTP '+a.status:'')+' · 容器 '+(a.container?a.container.slice(0,12):'未派入'),attemptTone(a));
 if(a.response)text(block,'p','回复摘要：'+a.response.slice(0,16)+'…');});
 if(group.truncated)text(block,'p','记录超过页面上限，需查询完整本地记录。');}
 status.className='';status.textContent='更新于 '+new Date().toLocaleTimeString();
 }catch(e){renderLogging(null);status.textContent=e.message;status.className='error';for(const id of ['count-all','count-ready','count-pending'])document.querySelector('#'+id).textContent='—';document.querySelectorAll('.account-card').forEach(cardMotion.remove);accounts.replaceChildren();const failure=text(accounts,'div','','empty');text(failure,'h3','暂时无法读取账号状态');text(failure,'p','请检查管理服务连接后重试。当前页面不显示过期的接单状态。');const retry=text(failure,'button','重新读取');retry.onclick=()=>refresh(true);document.querySelector('#requests').replaceChildren();}finally{busy=false;if(focusKey){[...document.querySelectorAll('[data-focus-id]')].find(el=>el.dataset.focusId===focusKey)?.focus({preventScroll:true});}}}
const selectedAccount=new URLSearchParams(location.search).get('account');if(selectedAccount)document.querySelector('#account-search').value=selectedAccount;
document.querySelector('#refresh').addEventListener('click',()=>refresh(true));refresh();setInterval(()=>{if(!document.hidden)refresh();},5000);

async function operate(slug,action){
 if(working||confirming)return;
 if(action==='restart'){
  confirming=true;const dialog=document.querySelector('#restart-dialog');document.querySelector('#restart-account').textContent=currentProjects.find(p=>p.slug===slug)?.label||slug;dialog.returnValue='';
  const accepted=await new Promise(resolve=>{dialog.addEventListener('close',()=>resolve(dialog.returnValue==='confirm'),{once:true});dialog.showModal();});confirming=false;if(!accepted)return;
 }
 if(action==='auth-cancel'){
  confirming=true;const dialog=document.querySelector('#cancel-auth-dialog');document.querySelector('#cancel-auth-account').textContent=currentProjects.find(p=>p.slug===slug)?.label||slug;dialog.returnValue='';
  const accepted=await new Promise(resolve=>{dialog.addEventListener('close',()=>resolve(dialog.returnValue==='confirm'),{once:true});dialog.showModal();});confirming=false;
  if(!accepted)return;
 }
 working=true;const progress=document.querySelector('#progress');
 const messages={'account-update':'正在通过此账号容器查询订阅档位和额度…','backup-export':'已请求更新加密备份，执行器继续运行…','backup-restore':'正在验证备份并恢复到新数据卷，保留原数据…','retry-backup':'正在使用已保存的授权重新备份和校验，不重新登录…',create:'正在校验代理配置、准备容器并检查网络…','auth-begin':'正在启动容器浏览器和授权回调…','open-browser':'正在恢复窗口并连接原来的容器浏览器…','close-browser':'正在关闭容器浏览器…','auth-complete':'正在保存凭据、关闭浏览器并校验完整环境备份…','auth-cancel':'正在取消授权…','auth-refresh':'正在立即刷新凭据；有效访问凭据仍可接单…',restart:'正在重启并核对持久状态…'};
 progress.textContent=action==='proxy-view'?'正在读取此账号已绑定的 SOCKS 地址…':messages[action];document.querySelectorAll('article button').forEach(b=>b.disabled=true);
 if(action==='create'){const card=[...accounts.querySelectorAll('.account-card')].find(c=>c.dataset.account===slug);if(card)text(card.querySelector('.card-main'),'p','正在提交创建请求…','creation-submitting').setAttribute('role','status');}
 try{const body={slug,action};if(action==='create')body.proxy_url=proxies[slug];if(action==='auth-complete')body.state=pending[slug];
 const r=await fetch('/action',{method:'POST',headers:{'Content-Type':'application/json','X-Offline-View':sessionStorage.getItem(tokenKey)},body:JSON.stringify(body)});const data=await r.json();
 if(!r.ok){const code=data.error?.message||data.error;throw Error(labels[code]||'刷新或操作未完成，请查看账号的服务状态与刷新状态。');}
 if(data.viewer_url){viewers[slug]=data.viewer_url;if(action==='auth-begin')trackedAuthorization=slug;}
 if(action==='close-browser'||action==='restart')delete viewers[slug];
 if(action==='proxy-view')revealedProxies[slug]=data.proxy_url;
 if(action==='create')delete proxies[slug];
 if(action==='auth-complete'||action==='auth-cancel')delete pending[slug];
 if(action==='auth-cancel'){delete viewers[slug];if(trackedAuthorization===slug)trackedAuthorization='';}
 progress.textContent=action==='account-update'?(data.ok?'账号档位与额度已更新。':data.partial?'部分资料更新成功；失败项目保留旧值，请查看卡片提示。':'本次查询未成功，已有资料保留；请查看卡片提示。'):action==='proxy-view'?'已显示此账号绑定的 SOCKS 地址。':action==='auth-cancel'?'已取消本次授权并关闭浏览器，账号与容器保留。':data.queued?'加密备份已排队，稍后自动更新结果；不额外停止调用。':data.viewer_url?(action==='auth-begin'?'浏览器已启动，请点击「进入容器浏览器」完成授权；完成后自动关闭并备份。':'原账号容器浏览器已打开，请点击「进入容器浏览器」。未重新发起授权。'):'操作已完成，账号状态已更新。';
 }catch(e){progress.textContent=e.message;}finally{working=false;await refresh(true);}
}

const accountForm=document.querySelector('#account-form');
accountForm.addEventListener('submit',async event=>{
 event.preventDefault();if(working)return;working=true;
 const feedback=document.querySelector('#account-feedback'),submit=document.querySelector('#account-submit');submit.disabled=true;feedback.className='';feedback.textContent='正在保存账号记录…';
 try{
  const proxy=document.querySelector('#account-proxy').value.trim();
  let parsed;try{parsed=new URL(proxy);}catch{throw Error('请填写有效的 SOCKS 地址。');}if(!['socks5:','socks5h:'].includes(parsed.protocol)||!parsed.hostname||!parsed.port)throw Error('请填写完整的 SOCKS5 地址和端口。');
  const body={action:'register-auto',provider:document.querySelector('#account-provider').value};
  const response=await fetch('/action',{method:'POST',headers:{'Content-Type':'application/json','X-Offline-View':sessionStorage.getItem(tokenKey)},body:JSON.stringify(body)});
  const value=await response.json();if(!response.ok)throw Error(labels[value.error?.message||value.error]||'账号未保存，请检查配置后重试。');
  proxies[value.slug]=proxy;accountForm.reset();trackedAuthorization='';showAdd(false);working=false;await refresh(true);await operate(value.slug,'create');
 }catch(error){feedback.className='error';feedback.textContent=error.message;}
 finally{working=false;submit.disabled=false;await refresh(true);}
});

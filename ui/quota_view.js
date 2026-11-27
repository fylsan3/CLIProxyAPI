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


// Explicit reported subscription fields only; no inference from usage or token lifetime.
function subscriptionLabel(state){
 const p=state?.account_observation?.profile?.values||{},v={...(state?.subscription||{}),...p};
 const raw=[v.subscription_type,v.plan_type,v.rate_limit_tier,v.organization_type].filter(Boolean).join(' · ');
 // Official naming checked 2026-11-25: Max 20x migrated to Ultra; Max 5x is Max.
 // Legacy upstream tier identifiers remain valid evidence; do not alter stored data or quota windows.
 if(/\bultra\b|claude_ultra|max[_ -]?20x/i.test(raw))return 'Ultra';
 if(/\bpro\b|claude_pro/i.test(raw))return 'Pro';if(/max/i.test(raw))return 'Max';
 if(/\bfree\b|claude_free/i.test(raw))return 'Free';return raw||'档位未报告';
}
function accountQuotaWindows(state){
 const active=state?.account_observation?.usage,passive=state?.quota_observation;
 const headers=Object.fromEntries(Object.entries(passive?.signals||{}).map(([k,v])=>[k.toLowerCase(),v]));
 const definitions=[['five_hour','5h','5 小时'],['seven_day','7d','7 天']];
 for(const [key,short,label] of [['seven_day_opus','7d_opus','Opus · 7 天'],['seven_day_sonnet','7d_sonnet','Sonnet · 7 天'],['seven_day_oi','7d_oi','Fable 5 · 7 天']]) {
  if(active?.values?.[key]||headers['anthropic-ratelimit-unified-'+short+'-utilization']!==undefined)definitions.push([key,short,label]);
 }
 const limits=Array.isArray(active?.values?.limits)?active.values.limits:[];
 const fables=limits.filter(x=>x?.kind==='weekly_scoped'&&/^fable( 5)?$/i.test(x.scope?.model?.display_name||''));
 const fable=fables.find(x=>x.is_active===true)||fables[0];
 const legacy=active?.values?.iguana_necktie;
 const fableValue=fable?{utilization:fable.percent,resets_at:fable.resets_at,is_active:fable.is_active}:legacy&&!['limit_dollars','used_dollars','remaining_dollars'].some(k=>legacy[k]!==undefined)?legacy:undefined;
 if(fableValue&&!definitions.some(x=>x[0]==='seven_day_oi'))definitions.push(['seven_day_oi','7d_oi','Fable 5 · 7 天']);
 return definitions.map(([key,short,label])=>{
  const value=key==='seven_day_oi'?(fableValue||active?.values?.[key]):active?.values?.[key],prefix='anthropic-ratelimit-unified-'+short+'-';
  const ratio=headers[prefix+'utilization'],n=ratio!==undefined&&String(ratio).trim()!==''?Number(ratio):NaN;
  const valid=Number.isFinite(n)&&n>=0&&n<=1;
  const activeStamp=Date.parse(active?.observed_at||''),passiveStamp=Date.parse(passive?.observed_at||'');
  // Missing/null/invalid values are not zero usage. Do not let an incomplete
  // newer record erase a valid earlier observation.
  const activeValid=Number.isFinite(value?.utilization)&&value.utilization>=0&&value.utilization<=100;
  const activeNewer=Number.isFinite(activeStamp)&&(!Number.isFinite(passiveStamp)||activeStamp>=passiveStamp);
  if(value?.is_active===false&&(!valid||activeNewer))return {label,active:false,reset:value.resets_at,stamp:active?.observed_at,source:'资料查询'};
  if(activeValid&&(!valid||activeNewer))return {label,percent:value.utilization,reset:value.resets_at,stamp:active?.observed_at,source:'资料查询'};
  return {label,percent:valid?n*100:undefined,reset:/^[0-9]+$/.test(headers[prefix+'reset']||'')&&Number.isFinite(new Date(Number(headers[prefix+'reset'])*1000).getTime())?new Date(Number(headers[prefix+'reset'])*1000).toISOString():undefined,stamp:passive?.observed_at,source:'模型回复'};
 }).filter(item=>item.label!=='Fable 5 · 7 天'||Number.isFinite(item.percent)||item.active===false);
}
function quotaCountdown(reset,now=Date.now()){
 const end=Date.parse(reset||'');if(!Number.isFinite(end))return '重置时间未报告';
 const minutes=Math.ceil((end-now)/60000);if(minutes<=0)return '已到重置时间，待更新';
 const days=Math.floor(minutes/1440),hours=Math.floor(minutes%1440/60),mins=minutes%60;
 return days?'距重置 '+days+'天 '+hours+'小时':hours?'距重置 '+hours+'小时 '+mins+'分钟':'距重置 '+mins+'分钟';
}
function renderAccountQuota(parent,p,showDetails=false){
 const wrap=text(parent,'section','','account-quota');wrap.setAttribute('aria-label','订阅额度');
 const sources=new Map();
 for(const item of accountQuotaWindows(p.state)){
  // A reported disabled window is useful in details, not an available card quota.
  if(!showDetails&&item.label==='Fable 5 · 7 天'&&item.active===false)continue;
  const stale=Number.isFinite(Date.parse(item.reset||''))&&Date.parse(item.reset)<=Date.now();
  const valid=Number.isFinite(item.percent)&&item.percent>=0&&item.percent<=100,remaining=valid?100-item.percent:undefined;
  const tone=stale?'quota-stale':valid&&remaining<30?'quota-danger':valid&&remaining<70?'quota-warning':'';
  const row=text(wrap,'div','','quota-window '+tone),heading=text(row,'div','','quota-heading'),label=text(heading,'span','');text(label,'span',item.label);
  text(heading,'strong',item.active===false?'未启用':valid?(stale?'上次剩余 ':'剩余 ')+Number(remaining.toFixed(2))+'%':'未报告');
  if(item.reset&&Number.isFinite(Date.parse(item.reset)))row.title='上游所报重置时间：'+new Date(item.reset).toLocaleString();
  if(item.active===false)text(row,'p','上游标记此额度未启用；不作为可用额度。','help');
  else {const meter=text(row,'div','','quota-meter');if(valid){meter.setAttribute('role','progressbar');meter.setAttribute('aria-label',item.label+(stale?'上次剩余额度':'剩余额度'));meter.setAttribute('aria-valuenow',String(remaining));meter.setAttribute('aria-valuemin','0');meter.setAttribute('aria-valuemax','100');const fill=text(meter,'span','');fill.style.width=remaining+'%';}}
  if(item.active!==false)text(showDetails?row:label,'small',quotaCountdown(item.reset),showDetails?'quota-countdown':'quota-inline-countdown');
  if(item.stamp){const date=new Date(item.stamp),key=item.source+' · '+(Number.isFinite(date.getTime())?date.toLocaleString():'观测时间未知');sources.set(key,[...(sources.get(key)||[]),item.label]);}
 }
 if(showDetails)for(const [stamp,labels] of sources)text(wrap,'p',(sources.size>1?labels.join('、')+' · ':'')+stamp,'help');
 const observation=p.state?.account_observation;
 for(const [key,label] of [['profile','档位'],['usage','额度']])if(observation?.[key]?.error)text(wrap,'p',label+'查询失败；'+(observation[key].observed_at?'显示上次成功结果。':'尚无结果。'),'status-bad');
 const capture=observation?.capture;
 if(showDetails&&capture)text(wrap,'p',capture.state==='complete'?'本次完整 HTTP 样本已加密保存 · '+capture.id:'本次 HTTP 样本未完整保存，不能用于完整重放。',capture.state==='complete'?'help':'status-bad');
 if(showDetails)text(wrap,'p','上次观测结果；到重置时间后需更新确认。','help');
}

function resetGrantSummary(state,now=Date.now()){
 const observation=state?.account_observation?.usage,block=observation?.values?.cedar_ember;
 if(!block)return {reported:false,error:observation?.error};
 const grants=Array.isArray(block.grants)?block.grants:[];
 let left=0,known=true,usable=0;
 for(const g of grants){
  if(!Number.isInteger(g.resets_left)||g.resets_left<0){known=false;continue;}
  const expired=g.ends_at&&Date.parse(g.ends_at)<=now;
  if(!expired)left+=g.resets_left;
  if(!expired&&block.eligible===true&&g.usable_now===true&&g.paused===false&&g.resets_left>0&&(!g.starts_at||Date.parse(g.starts_at)<=now)&&(!block.cooldown_until||Date.parse(block.cooldown_until)<=now)&&(g.use_requires_limit===false||block.at_limit===true))usable+=g.resets_left;
 }
 return {reported:true,left:known?left:undefined,usable,grants,stamp:observation.observed_at,error:observation.error};
}
function renderResetGrants(parent,p,showDetails=false){
 const view=resetGrantSummary(p.state);
 if(!view.reported||!(view.left>0))return;
 const section=text(parent,'section','','account-quota reset-grants');
 section.setAttribute('aria-label','重置卡');text(section,'strong','重置卡');
 if(!view.reported){text(section,'p','尚未报告；点击「刷新用量」读取。','help');return;}
 text(section,'p','剩余 '+(view.left===undefined?'未报告':view.left)+' 次 · 上次报告可用 '+view.usable+' 次');
 if(!showDetails)return;
 for(const g of view.grants)if(g.ends_at)text(section,'p','有效期至 '+new Date(g.ends_at).toLocaleString(),'help');
 if(view.error)text(section,'p','本次读取失败，保留上次结果。','status-bad');
 text(section,'p','目前仅展示，消耗入口尚未开放；刷新用量不会使用重置卡。','help');
}

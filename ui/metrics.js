/* Passive local dashboard observations; never make an account/provider request. */
function metricNumber(value){return Number.isFinite(value)?new Intl.NumberFormat('zh-CN',{notation:value>=10000?'compact':'standard',maximumFractionDigits:1}).format(value):'未统计';}
function resourceBytes(value){if(!Number.isFinite(value))return '未统计';return value>=1073741824?(value/1073741824).toFixed(2)+' GiB':Math.round(value/1048576)+' MiB';}
function relativeRequest(value){if(!Number.isFinite(value))return '暂无请求';const s=Math.max(0,Date.now()/1000-value);return s<60?'刚刚':s<3600?Math.floor(s/60)+' 分钟前':s<86400?Math.floor(s/3600)+' 小时前':Math.floor(s/86400)+' 天前';}
const statusExpanded=new Set();
function renderStatusSummary(parent,p){
 const box=text(parent,'div','','status-summary');box.hidden=!statusExpanded.has(p.slug);
 const states=[['容器',p.container?(p.reason==='container_stopped'?'已停止':p.reason==='worker_unavailable'?'执行器不可用':'已创建'):'尚未创建',!['container_stopped','worker_unavailable'].includes(p.reason)&&!!p.container],['账号网络',p.network?(p.network.healthy?'检查通过':'检查未通过'):'等待检查',p.network?.healthy],['凭据',p.state?.authorized?'已授权':'等待授权',p.state?.authorized],['调度',p.overall_ready?'允许接单':labels[p.reason]||'暂不可接单',p.overall_ready]];
 for(const [label,value,ok] of states){const row=text(box,'p','');text(row,'span',label);text(row,'strong',value,ok?'status-ok':accountTone(p));}
 return box;
}
function renderActivity(parent,p){
 const box=text(parent,'div','','account-metrics'),a=p.activity,r=p.resource_sample;
 const memory=r&&!r.error&&!r.stopped&&Date.now()/1000-r.at<=90?r:p.state?.resources;
 const row=(label,value,title)=>{const e=text(box,'p','');text(e,'span',label);const strong=text(e,'strong',value);if(title)strong.title=title;return e;};
 const current=memory?.memory_bytes??memory?.memory_current_bytes,limit=memory?.memory_limit_bytes,peak=memory?.memory_peak_bytes;
 const mem=row('内存',Number.isFinite(current)?Math.round(current/1048576)+' / '+(Number.isFinite(limit)?Math.round(limit/1048576):'—')+' MiB':'未统计');
 const peakText=text(mem,'span','峰值 '+(Number.isFinite(peak)?Math.round(peak/1048576)+' MiB':'未统计'));peakText.title='当前容器所报告的内存峰值';
 row('最近请求',relativeRequest(a?.last_request_at),a?.last_request_at?new Date(a.last_request_at*1000).toLocaleString():undefined);
 const t=p.usage?.totals,total=Number.isFinite(t?.input_tokens)&&Number.isFinite(t?.output_tokens)?t.input_tokens+t.output_tokens:null;
 row('累计用量',metricNumber(total)+(total!==null?' Token':''),'已确认输入＋输出 Token，不代表金额；缓存读取/写入在详情查看');
 const week=row('近 7 天','');week.lastElementChild.remove();const values=text(week,'span','成功 ');text(values,'b',metricNumber(a?.seven_day?.success),a?'status-ok':'');text(values,'span',' · 失败 ');text(values,'b',metricNumber(a?.seven_day?.failed),a?.seven_day?.failed>0?'status-bad':'');week.title='按账号执行次数统计，含重试；待确认 '+metricNumber(a?.seven_day?.unknown)+'，处理中 '+metricNumber(a?.seven_day?.active);
 const rates=text(box,'div','','account-rates');for(const [label,value,tip] of [['RPM',a?.rpm,'最近 60 秒执行次数'],['TPM',a?.tpm,'最近 60 秒结束的请求，已确认输入＋输出 Token；历史无完成时间不计入'],['峰值 RPM',a?.peak_rpm,'近 7 天滚动 60 秒最大执行次数']]){const e=text(rates,'span',label+' ');text(e,'b',metricNumber(value)+(label==='TPM'&&a?.tpm_incomplete?'*':''));e.title=tip;}
 if(a?.tpm_incomplete)text(box,'p','* 部分请求未报告完整 Token','help');
}
let resourceRange='1h',resourceView=null,resourceExpanded=false;
function renderResourceMonitor(value){
 resourceView=value;const host=document.querySelector('#resource-monitor');if(!host)return;
 if(!host.children.length){
  const toggle=text(host,'button','','monitor-toggle');toggle.type='button';toggle.dataset.focusId='resources:toggle';toggle.setAttribute('aria-controls','resource-monitor-details');
  const title=text(toggle,'span','','monitor-title');text(title,'small','','monitor-freshness');
  const totals=text(toggle,'span','','monitor-totals');totals.id='resource-summary-values';toggle.setAttribute('aria-describedby',totals.id);
  for(const [key,label] of [['memory_bytes','内存'],['cpu_percent','CPU'],['disk_bytes','数据盘']]){const item=text(totals,'span','','monitor-total');text(item,'span',label);const val=text(item,'strong','未统计');val.dataset.metric=key;}
  toggle.onclick=()=>{resourceExpanded=!resourceExpanded;renderResourceMonitor(resourceView);};
  host.closest('.overview').addEventListener('click',event=>{
   if(event.target.closest('.monitor-toggle,.monitor-details'))return;
   toggle.click();
  });
  const details=text(host,'div','','monitor-details');details.id='resource-monitor-details';details.hidden=true;details.append(document.querySelector('#status'));
  const heading=text(details,'div','','monitor-heading');text(heading,'h2','历史趋势');const ranges=text(heading,'div','','monitor-ranges');ranges.setAttribute('aria-label','监控时间范围');
  for(const [id,label] of [['1h','近 1 小时'],['24h','近 24 小时'],['7d','近 7 天']]){const b=text(ranges,'button',label,'secondary');b.dataset.focusId='resources:'+id;b.dataset.range=id;b.onclick=()=>{resourceRange=id;renderResourceMonitor(resourceView);};}
  text(details,'p','','monitor-status help');text(details,'div','','monitor-charts');text(details,'p','总计仅包含本 CPA 绑定账号容器。CPU 100% = 1 个核心；数据盘含环境、容器备份与网络配置，不含共享镜像和主机导出包。内存/CPU 每 30 秒采集，磁盘每 5 分钟。','monitor-help');
 }
 for(const b of host.querySelectorAll('[data-range]'))b.setAttribute('aria-pressed',String(b.dataset.range===resourceRange));
 const latest=value?.current,stale=!value||value.stale;
 const toggle=host.querySelector('.monitor-toggle');toggle.setAttribute('aria-expanded',String(resourceExpanded));host.querySelector('.monitor-details').hidden=!resourceExpanded;
 toggle.setAttribute('aria-label',resourceExpanded?'收起容器资源监控':'展开容器资源监控');toggle.title=resourceExpanded?'点击收起曲线':'点击查看曲线';
 const freshness=host.querySelector('.monitor-freshness');freshness.textContent=!value?'等待数据':stale?'数据已过期':latest?.missing_accounts?'部分数据缺失':'';host.querySelector('.monitor-title').hidden=!freshness.textContent;freshness.title='资源采样状态';freshness.classList.toggle('status-bad',!!value&&(stale||latest?.missing_accounts>0));
 const formats={memory_bytes:resourceBytes,cpu_percent:v=>Number.isFinite(v)?v.toFixed(1)+'%':'未统计',disk_bytes:resourceBytes};
 for(const item of host.querySelectorAll('[data-metric]'))item.textContent=formats[item.dataset.metric](stale?null:latest?.[item.dataset.metric]);
 if(!resourceExpanded)return;
 host.querySelector('.monitor-status').textContent=!value?'监控尚未就绪':stale?'暂未收到新资源数据，历史记录保留；当前值不作为实时状态。':'共 '+latest.accounts+' 个账号容器 · 更新于 '+new Date(latest.at*1000).toLocaleTimeString()+' · 历史从 '+new Date(value.history_since*1000).toLocaleString()+' 开始';
 const charts=host.querySelector('.monitor-charts');charts.replaceChildren();const points=value?.series?.[resourceRange]||[];
 for(const [key,label,format] of [['memory_bytes','总内存',resourceBytes],['cpu_percent','总 CPU',v=>Number.isFinite(v)?v.toFixed(1)+'%':'未统计'],['disk_bytes','账号数据盘',resourceBytes]]){
  const figure=text(charts,'figure','','resource-chart');const caption=text(figure,'figcaption','');text(caption,'span',label);text(caption,'strong',format(stale?null:latest?.[key]));
  const valid=points.filter(p=>Number.isFinite(p[key]));const note=text(figure,'p',valid.length?'区间采样峰值 '+format(Math.max(...valid.map(p=>p[key+'_peak']??p[key]))):'等待有效采样','chart-caption');
  const ns='http://www.w3.org/2000/svg',svg=figure.ownerDocument.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 300 84');svg.setAttribute('role','img');svg.setAttribute('aria-label',label+'历史趋势');svg.setAttribute('tabindex','0');figure.append(svg);
  if(!valid.length){text(figure,'p','暂无数据','chart-empty');continue;}
  const now=value.observed_at,start=now-({'1h':3600,'24h':86400,'7d':604800}[resourceRange]),max=Math.max(1,...valid.map(p=>p[key]));const x=p=>Math.max(0,Math.min(300,(p.at-start)/(now-start)*300)),y=p=>76-p[key]/max*68;
  let d='',prior=null;const gap=({'1h':90,'24h':900,'7d':10800}[resourceRange]);
  for(const p of points){if(!Number.isFinite(p[key])){prior=null;continue;}d+=(prior&&p.at-prior.at<=gap?'L':'M')+x(p).toFixed(2)+' '+y(p).toFixed(2)+' ';prior=p;}
  const line=figure.ownerDocument.createElementNS(ns,'path');line.setAttribute('d',d);line.setAttribute('fill','none');line.setAttribute('stroke','currentColor');line.setAttribute('stroke-width','2');svg.append(line);
  const dot=figure.ownerDocument.createElementNS(ns,'circle');dot.setAttribute('r','3');dot.setAttribute('fill','currentColor');svg.append(dot);let selected=valid.length-1;
  function show(i){selected=Math.max(0,Math.min(valid.length-1,i));const p=valid[selected];dot.setAttribute('cx',x(p));dot.setAttribute('cy',y(p));note.textContent=new Date(p.at*1000).toLocaleString()+' · '+format(p[key]);}
  dot.setAttribute('cx',x(valid[selected]));dot.setAttribute('cy',y(valid[selected]));
  svg.onpointermove=e=>{const px=(e.clientX-svg.getBoundingClientRect().left)/svg.getBoundingClientRect().width*300;show(valid.reduce((best,p,i)=>Math.abs(x(p)-px)<Math.abs(x(valid[best])-px)?i:best,0));};
  svg.onkeydown=e=>{if(['ArrowLeft','ArrowRight'].includes(e.key)){e.preventDefault();show(selected+(e.key==='ArrowRight'?1:-1));}};
  const axis=text(figure,'div','','chart-axis');text(axis,'span',new Date(start*1000).toLocaleString());text(axis,'span','现在');
 }
}

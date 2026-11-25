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


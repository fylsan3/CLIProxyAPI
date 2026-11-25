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
 const header=text(block,'div','','creation-heading');text(header,'h3',failed?'创建失败':running?'正在创建环境':'环境启动完成',failed?'status-bad':running?'':'status-ok');
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

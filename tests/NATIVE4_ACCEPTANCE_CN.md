# container-native4 离线验收记录（2026-11-25）

本次只使用虚构 A/B、封闭 TLS 模拟上游和临时 NewAPI 数据库。生产、真实订阅账号、内网 NewAPI 未改。所有本次测试资源均已清理。

## 新增模型入口与回复

A/B × Messages、Chat Completions、Completions、Responses、Gemini × 普通/流式：20 组通过。原版 Responses WebSocket 和 compact：通过。Chat/Responses 工具返回以及 403 错误详情：通过。Messages 原有同协议转发未改为跨协议。

## NewAPI 对接与额度

实际 NewAPI 服务代码连接隔离 CPA：列表、用量资料查询、停用/启用、代理查看和模型列表通过；另有隔离 HTTP 测试确认令牌刷新使用容器动作、不再下载凭据或调用旧 api-call。不支持的重置卡领取在服务器端明确拒绝。

Fable scoped limit 已用 90% → 5%（对应剩余 10% → 95%）同步通过；未授权任意 profile/scope 字段未进入管理数据。CPA 卡片取值测试通过；NewAPI 20 项前端用量测试通过。到历史重置时间时容器卡片不伪造满额。

## 原始用量回执

新增私有用量回执直接复制原版 UsageReporter 的 usage.Detail；没有从 Gemini/其他转换后的响应倒推缓存拆分。冻结源文件不动，usage_helpers.go overlay 相对原版只增加一行只读捕获调用。

5 协议 × 普通/流式共 10 组：原始输入 9、输出 3、缓存创建 4、缓存读取 7 在中央原版用量队列保持一致，账号汇总匹配。客户端没有收到 X-Offline-* 内部回执头。用量队列仍由原版 usage-statistics-enabled 开关控制。

## 环境与构建

OS/架构实际本地出站捕获、持久基线重新加载、OS/架构不符拒绝、测试容器重启后凭据和环境保留均通过。没有进行异机恢复。

Mac ARM64 中央运行、Ubuntu Linux ARM64 执行器运行、Linux ARM64 中央编译。NewAPI 完整 Mac 后端和前端生产构建、类型检查、涉及文件 lint、针对性后端测试通过。原版 source、冻结 management.html、手动头基线保持不变。

## 未完成的外部验证

生产切换尚未执行；目标 Linux 服务器与真实订阅接口还未验证。官方环境下首次任务应留存脱敏请求样本，沿用现有授权/环境，不能重新登录或以模拟结果宣称真实订阅可用。

下一步：部署配套 CPA 与 NewAPI 后做一次真实联调。一小时长任务继续保留待验收提醒；异机备份恢复已取消。重置卡领取仍不支持。

## 可复核结果

### multiprotocol-chain

```json
{
  "real_accounts_used": false,
  "published": false,
  "browser_interaction_tested": false,
  "cases": {
    "A_messages": true,
    "A_messages_stream": true,
    "A_chat": true,
    "A_chat_stream": true,
    "A_completions": true,
    "A_completions_stream": true,
    "A_responses": true,
    "A_responses_stream": true,
    "A_gemini": true,
    "A_gemini_stream": true,
    "B_messages": true,
    "B_messages_stream": true,
    "B_chat": true,
    "B_chat_stream": true,
    "B_completions": true,
    "B_completions_stream": true,
    "B_responses": true,
    "B_responses_stream": true,
    "B_gemini": true,
    "B_gemini_stream": true,
    "fable_updated_snapshot_and_private_fields_removed": true,
    "restart_baseline_and_credentials_preserved": true,
    "wrong_binding_rejected": true,
    "native_usage_queue_contains_container_account_records": true,
    "multiprotocol_usage_receipts_confirmed": true,
    "newapi_actual_cpa_management_integration": true
  },
  "test_resources_removed": true
}
```

### protocol-extras

```json
{
  "real_accounts_used": false,
  "published": false,
  "browser_interaction_tested": false,
  "cases": {
    "chat_tool_preserved": true,
    "chat_denied_preserved": true,
    "responses_tool_preserved": true,
    "responses_denied_preserved": true,
    "native_responses_compact": true,
    "native_responses_websocket": true
  },
  "test_resources_removed": true
}
```

### protocol-cache

```json
{
  "real_accounts_used": false,
  "published": false,
  "browser_interaction_tested": false,
  "cases": {
    "messages_native_cache_counts": true,
    "messages_stream_native_cache_counts": true,
    "chat_native_cache_counts": true,
    "chat_stream_native_cache_counts": true,
    "completions_native_cache_counts": true,
    "completions_stream_native_cache_counts": true,
    "responses_native_cache_counts": true,
    "responses_stream_native_cache_counts": true,
    "gemini_native_cache_counts": true,
    "gemini_stream_native_cache_counts": true,
    "native_cache_receipts_match_account_totals": true
  },
  "test_resources_removed": true
}
```

最终 worker SHA256：`2d1e881f1feed10b1ca59ac7f6db4532482af28fae861a5f0633fc725b520df3`。

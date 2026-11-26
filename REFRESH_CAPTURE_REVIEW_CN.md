# 用量刷新与采样状态检查 — 2026-11-26

本轮不修改 Go 执行器、请求头策略、客户正文或原生签名处理。不调用真实订阅接口。仅更新中央管理回执、页面与本地采样解释层。

## cc_version 的来源

位置是请求 JSON 的 `system[0].text`，前缀 `x-anthropic-billing-header:`。名称中的 header 不代表 HTTP 请求头。

当前 worker 初始化及每请求配置都关闭 `DisableClaudeCloakMode` 对应的系统伪装开关，但原生签名流程是独立分支：
`ExecuteStream → claudeCCHFallbackBillingHeaderDoc → DefaultClaudeVersion → ensureClaudeBillingHeaderCCHPlaceholderDoc → prependClaudeBillingSystemBlockDoc`。
原生默认版本由 baseline User-Agent 解析，当前冻结源码为 `2.1.321`。末尾短摘要由请求文本取样与版本计算，不是用户 OS、浏览器版本或容器运行时。

本地实测：向中央 CPA 发送只有 `system: ORIGINAL_SYSTEM_CANARY` 与 `messages: hello` 的虚构请求。模拟上游观察到了新增 billing 文本，原有 system 文本仍保留。最终 HTTP 头覆盖器在后面执行，不改这段 JSON。所以关闭系统伪装不能被描述为“整个 CPA 绝不添加 system 内容”。对两条历史真实请求没有入站正文取证，不能单凭最终样本排除入站本来已有同类文本。

原生代码：`source/internal/runtime/executor/claude_executor_cloaking.go`、`claude_signing.go`、`helps/claude_device_profile.go`；实际流式路径 `src/internal/runtime/executor/claude_executor_stream.go:233`。

## 刷新用量

已使用真实管理页组件、虚构 A/B、原中央程序与原 worker、本地 TLS 模拟上游连通验证。链路：按钮 → 确认框 → 中央 `/v8/management/account-environments/action` → dashboard/action → broker/account-update → A worker `/auth/account-update` → profile 与 usage → 保存观测 → 页面。

- 取消及 Esc：零查询。
- 确认框等待超过 5 秒、经过自动状态轮询：仍等待确认，零查询。
- 确认一次：恰好一次 profile、一次 usage。
- usage 返回 403：部分成功，原用量与其观测时间保留，B 未收到额外查询。
- 未复现按钮不发请求；历史 POST 200 未保留动作/确认内容，不能补推上次原因。
- 新增本地操作 ID、四阶段回执、时间、状态码及档案 ID；不记录凭据、代理、客户内容或上游响应正文。详情中可见。失败不自动重试查询。

证据：`evidence/refresh-usage-chain.json`。第一次测试统计将同一请求的传输记录和业务记录重复计数；已按 https_request 计数修正，最终通过。原有创建状态测试缺少 MaintenanceGate 初始化，生产原代码已有该字段；只补测试夹具初始化后 9 项通过。

## 采样完整性

原生流式处理收到 `message_stop` 后停止读取；加密 HTTP 采样器只在 HTTP EOF 或完整 Content-Length 后判定完整。对 chunked 响应，消息结束而未确认 HTTP EOF 是可能且已观察到的状态。

新增解释层使用已脱敏 SSE 的顶层事件验证顺序，拒绝正文文本中的假 message_stop、缺失 stop_reason、重复/乱序/未终止事件及错误事件。严格区分：HTTP 原始响应完整性、模型消息结束、客户端是否接收完成。

两条既有样本 `650aa5fd102f67ce3ce41744-0001` 与 `e16eaa37127ad4d8445d3c20-0001` 均为：模型结束已观察；HTTP 结束未确认；客户端接收未观察；禁止作为完整原始 HTTP 重放。不会把历史 complete=false 改为 true，不清除历史审计证据，不读取额外流数据或延迟回复。

8 项针对性单元测试通过，覆盖完整/缺尾/错误 SSE、伪造结束文本、已有样本重分类、环境关联及脱敏管理回执。桌面与窄屏界面验证通过；只有消息结束经证据确认时才避免将 HTTP 未确认误显示为回复失败，真正未确认的流仍保留提示。

## 边界与后续

本轮没有改 Go 二进制或容器镜像，也没有更改手工设置的请求头。官方版本检查当日 npm 与 GitHub latest 为 2.1.332（https://registry.npmjs.org/@anthropic-ai/claude-code/latest ，https://github.com/anthropics/claude-code/releases/tag/v2.1.332）；本轮不声明执行器已完成该版本全面兼容验证。

后续仅在用户自然发出的请求上核对操作回执，不要求重复真实授权/查询。浏览器授权/验证码/回调及其头处理、重置卡消费、一小时长任务仍待验收。当前状态修正不等同于所有历史样本已具备完整 HTTP 重放条件。

# container-native4：NewAPI 对接、多协议入口和环境基线

日期：2026-11-25。源码候选，未切换生产，未访问真实订阅账号或内网 NewAPI。

## 本次范围

- 保留 CPA 8.1.1 原版 Chat Completions、Completions、Responses、Gemini 处理器和转换器；中央只选择账号，转换及 Claude 模型执行仍在账号自己的容器。Messages 保持已有同协议直通。
- 请求协议、回复协议、模型名、流式模式及 compact 标记放在内部派单封包；不靠改写客户正文补模型名。内部控制字段不能由客户请求头覆盖，也不向 Anthropic 转发。
- 跨协议流式分块在内部封包后还原，交还原版协议处理器。跨协议结构必须转换，不能承诺与 Anthropic SSE 逐字节相同；同协议路径仍不改正文。
- 中央使用原生 UsageReporter 发布用量队列，保持 auth_index 与容器账号对应。容器在原版 reporter 发布时只读取得原始 usage.Detail，通过私有回执/尾部字段传回中央，不从跨协议回复倒算缓存计数。这些内部字段不返回客户。此队列须启用原有 usage-statistics-enabled 配置；NewAPI 仍使用原版读取接口。
- 停用/启用写入容器账号持久路由元数据，由原版账号选择器与容器派单门共同执行。不得退回宿主机执行。

## NewAPI 源码对接

仓库：fylsan3/new-api，分支 feat/subscription-accounts。

识别 credentials.source=container 后，读取 CPA 返回的非敏感 account_observation / quota 快照。手动查询资料用量、刷新访问令牌和查看代理改走 account-environments/action，模型列表沿用 credentials/models，停用/启用使用接入容器的 credentials/status。不会下载订阅凭据、使用旧 api-call 代发查询，或直接连接 Anthropic。旧版 CPA 账号分支仍保留。

现有五秒本地账号同步会同步更新的用量快照，不额外访问 Anthropic。旧版每日上游查询任务对于容器账号只导入已有快照；主动查询保留在明确的“刷新用量”操作中。真实授权、刷新有效性仍须官方端验证。

重置卡：当前容器 CPA 没有实现领取/消耗接口。NewAPI 清除不适用的旧卡缓存并明确拒绝领取，不回退到宿主机旧接口，不自动消耗任何卡。

## Fable 5

原版冻结 management.html 已包含 Fable 5 标签以及 limits / weekly_scoped / scope.model.display_name / percent 解析；NewAPI 原有卡片也支持该格式。容器版此前 cleanUsage 只保留五种顶层窗口，遗漏 limits，属于本次修复的明确差异。

本次保留有结构校验的额度窗口、Fable limits，以及需要的重置时间；不带入任意 profile、scope 或凭据字段。CPA 卡片和 NewAPI 均能展示新数据，较新的 7d_oi 模型回复观测也能更新 Fable 窗口。

离线验证已用 90% → 5%，剩余展示应为 10% → 95%。这是上游报告变化的同步，不是本地发放额度。容器账号到达历史重置时间后保留上次值，等待新观测，不自动显示为满额；查询失败保留旧值与错误提示。

## OS / 架构

创建时已有 retention.json 保存架构及 /etc/os-release 摘要，且纳入初始环境备份。新执行器从这份可信记录加载基线，在网络检查之后、凭据读取之前核对实际 Linux/架构及 OS 发行信息摘要。通过后将 X-Stainless-OS / X-Stainless-Arch 的值固定在该进程内，后续请求不重新取客户/宿主信息。

重启或恢复时先验证实际容器与持久记录一致；架构或 OS 内容不符拒绝启动，不用旧值掩盖真实变化。现有账号无需重新采样设备标识或重新授权。其余手动请求头、时区、语言和客户正文均未调整。此检查不固定宿主 Linux 内核版本，也不是浏览器所有可观察属性的保证。

## 升级检查

本次从官方 GitHub release 与 npm latest 都核对为 Claude Code 2.1.332：
- https://github.com/anthropics/claude-code/releases/tag/v2.1.332
- https://registry.npmjs.org/@anthropic-ai/claude-code/latest

官方原包在 Ubuntu Linux ARM64、隔离配置、非交互 -p、虚构 API key、无外网及回环模拟服务中运行，收到模拟 OK。
官方样本：Linux/arm64；Anthropic-Version 2023-06-01；UA 2.1.332；node/v26.12.1；SDK 0.128.0。当前 Go 候选保留用户既有手动声明（含 UA 2.1.331、Node/SDK 声明），未据此冒充升级后的官方客户端。OS/架构来自上面的真实环境基线，功能转换来自冻结 CPA 原版。官方样本里的身份、会话及客户正文不复制。

原始离线采样仅留本机 work/client-version-audit-20261125，不提交账号、凭据、原始用户请求或生产配置。此普通 API key 模拟采样不能证明真实订阅权限或官方识别结果。

## 验证记录

- Mac ARM64：中央程序编译；中央＋Docker 隔离 A/B 集成运行。
- Ubuntu Linux ARM64：账号 Go 执行器实际执行，Linux 中央程序编译。不是独立 Linux 目标服务器部署验收；此仓库当前仍是 ARM64 构建范围。
- A/B × Messages / Chat / Completions / Responses / Gemini × 普通 / 流式：20 组通过，回复与容器归属及用量回执对应。
- Fable 快照更新、敏感字段裁剪、持久停用/启用、错误账号绑定拒绝、原版用量队列：通过。
- NewAPI 实际管理代码连接上述隔离 CPA：账号同步、手动用量查询、停用/启用、查看代理、模型列表通过。
- OS/架构实际出站采集、同一持久基线重新加载、OS/架构不符拒绝，以及真实测试容器重启后凭据保留：通过。没有执行异机恢复。
- NewAPI 后端针对性测试、前端 20 个额度测试、类型检查、相关文件 lint、前端生产构建和完整 Mac 后端编译通过。
- Responses compact / WebSocket、跨协议工具与错误详细结果见 tests 下的离线验收记录。

## 待办及边界

1. 将已验证源码候选切换到本机生产，并由用户在内网部署配套 NewAPI；本次没有执行这两个部署动作。
2. 用户允许真实终验后，沿用原账号/容器、不退出不重新授权，先保存指定请求的脱敏样本，再核对官方模型响应、实际额度字段和刷新。
3. 一小时长任务仍需单独验收，每次讨论下一步保留提醒。异机备份恢复不再列入开发范围。
4. 目标 Linux 主机验证、真实上游模型/权限、重置卡领取仍未完成。模型及工具能力受原版 Claude 通道与实际上游支持约束，并非新增图片/音频等独立提供商。

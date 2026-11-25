# 容器系统与架构请求头检查（2026-11-25）

本次只调整模型发送层的 `X-Stainless-OS` 和 `X-Stainless-Arch`，适用于 `/v1/messages` 与 `/v1/messages/count_tokens`。在执行器进程所在容器内调用 `uname`，读取系统和机器架构，转换为请求头枚举；不使用中央控制器或客户电脑的信息。Linux/aarch64 对应 Linux/arm64，Linux/x86_64 对应 Linux/x64。未知值使用 Unknown/unknown。当前构建仍只支持 ARM64；x64 仅测试了名称映射。

## 三方对照与字段来源

| 项目 | 固定 CPA 源码 | 本次 Go 候选 | 官方 Claude Code 隔离样本 |
| --- | --- | --- | --- |
| OS/Arch | 原生 device profile 策略；默认映射 Go 的 GOOS/GOARCH，也可能采用 profile 或符合条件的来请求值 | 最终发送层以容器 uname 覆盖这两项；实测 Linux/arm64 | 2.1.332、Linux/arm64 |
| 协议版本 | 原生协议层处理 | 保留手动值 2023-06-01 | 2023-06-01 |
| 客户端及运行时声明 | 原生 profile/配置策略 | 其他 10 个手动覆盖值未改，包括历史 UA 2.1.331、node/v26.12.1、js、SDK 0.128.0；这些是声明，不是本次查询得到的 Go 运行环境 | UA 2.1.332、node/v26.12.1、js、SDK 0.128.0 |
| system/messages/tools/metadata | 原生转换逻辑 | 本补丁不修改正文、工具或标识；本次没有重新验收完整原生转换链路 | 样本含 model/messages/system/tools/metadata/max_tokens/thinking/context_management/output_config/stream；12 个工具 |
| 正文环境信息 | 依调用模式与原生逻辑决定 | 不把客户正文换成容器环境 | Platform、Shell、OS Version 在 messages.0.content.0.text：linux、bash、Linux 6.8.0-117-generic |

原生参考：`source/internal/runtime/executor/helps/claude_device_profile.go`。冻结源码及 `manual-header-reference.go.txt` 未修改；构建检查只允许上述两个容器字段偏离手动参考，其余字段必须一致。

## 时区与系统语言

当前最终请求头覆盖函数没有时区或系统语言替换。`X-Stainless-Lang: js` 表示程序语言声明，不是英语或中文。

容器启动参数另设 TZ 为账号卡片中的固定时区、LANG/LC_ALL 为 C.UTF-8、LANGUAGE 为 en_US:en。这些设置影响容器内程序自身，不会自动改写客户请求。现有英国容器只读检查为 Europe/London。

原生 CPA 有条件性的时区/日期上下文生成逻辑，但本执行器以 `DisableClaudeCloakMode: true` 创建原生执行器，不能把那条原生逻辑当成本通道已开启的时区清洗功能。本补丁不新增请求头、不修改客户内容、不清洗响应。

## 升级前官方版本核对

2026-11-25 核对官方 GitHub release 与 npm latest 为 2.1.332：

- https://github.com/anthropics/claude-code/releases/tag/v2.1.332
- https://registry.npmjs.org/@anthropic-ai/claude-code/latest
- 官方 Linux ARM64 包 `@anthropic-ai/claude-code-linux-arm64/2.1.332`；解包二进制 SHA256：`50c305fcb8912851ce774429131d94ed6f84edbe3d8d0ed7a59dade5d893acc0`。

官方原包在临时 Ubuntu ARM64 容器、独立 HOME、`--network none` 下运行，使用假 API key 和本地回环模拟上游。启动方式为 `claude -p --model claude-sonnet-4-6 --permission-mode dontAsk --strict-mcp-config --setting-sources user --no-session-persistence -- Please reply only OK.`；收到模拟 OK，退出码 0。未采用真实订阅 OAuth。原始脱敏审计文件保留在相邻 `client-version-audit-20261125` 工作目录，不随源码发布抓包内容。

## 本地验证与范围

`tests/container_platform_headers.py` 提取当前执行器实际的请求头函数，编译后放入无外网、无账号挂载的临时 Ubuntu 容器，向本地 HTTP 接收端发送请求。消息与 Token 计数两条路径均收到 Linux/arm64；与容器 uname 的 Linux/aarch64 对应。混合大小写重复输入被替换为单个值；其他 10 个手动字段与原参考一致。授权控制路径保持原处理方式。

测试另外主动构造了时区/语言测试标记，确认最终覆盖函数不会修改这些标记或正文；这不是实际客户端自然携带这些字段的证明，也不证明原生 CPA 的其他层会透传任意自定义头。该测试覆盖确切发送函数，不代表已跑通真实订阅全链路。

仍待验证：候选部署后的真实订阅模型请求、官方 OAuth 特有行为及目标机器的执行结果。没有修改生产服务、真实账号或现有 NewAPI。本地镜像构建不表示部署完成。

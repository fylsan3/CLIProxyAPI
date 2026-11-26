# 2026-11-26 文档整理前记录

本文件保存本次分类整理前的原文，只供追溯。下列引文中的“当前”“最新”“本轮”均指各自历史阶段，不是新的执行指令或当前生产状态。后来用户的明确授权不能被更早的阶段限制覆盖。原文中的状态、验证结果和作者归属，本次未重新核验。原文按整理时磁盘内容保存，未恢复此前已被删除的句子。

## 记录 1：AGENTS.md

```text
# Project working rules

## First check for Go executor upgrades

Before changing or releasing the Go executor, read
`work/client-version-audit/升级前必查.md`.

Treat comparison with the latest official Claude Code release as the first
upgrade compatibility check. Verify the current release at upgrade time; do not
treat a historical capture or installed client as the latest release.

Record launch mode, authentication path, platform, field provenance, and actual
outbound observations. Distinguish protocol compatibility from runtime and client
identity declarations. Do not blindly copy another client's identity, runtime,
account, session, device identifiers, or credentials. Do not rewrite customer
content to resemble a different execution environment.

An upgrade is not compatibility-verified until affected protocol differences
have been reviewed and tested. Clearly list cases still awaiting real-account
validation. A local mock capture cannot establish subscription endpoint behavior.

Keep frozen baseline files intact. Documentation updates do not authorize
production deployment, real-account calls, or changes to existing NewAPI services.
```

## 记录 2：work/client-version-audit/升级前必查.md

```text
# Claude Code / CPA 升级前优先核对

来源：用户 2026-11-24 明确要求每次更新时优先考虑真实最新版 Claude Code 的请求字段。

每次 Go 执行器升级，官方最新版 Claude Code 的协议兼容性与隐私字段对照是首要升级检查项，必须先于请求参数改动和兼容验收结论。该规则是开发检查项，不是定时任务或自动改写请求的任务。

## 用户要求与实施范围

用户原始要求（2026-11-24）：

> go执行器传输的参数在更新go执行器时必须严格按照官方最新版claudecode传什么参数，执行器就传输什么参数，这个优先级最高

实施规则：以官方最新版为协议兼容基准，逐项核对字段名称、类型、位置、用途和生成条件；不将上述要求执行为无条件复制所有字段和值。这里明确保留用户原始要求与实施边界的区别，不能声称已完成全部参数的一比一复制。

| 字段类别 | 升级处理规则 |
| --- | --- |
| 模型、工具、流式等功能协议字段 | 对应同一接口、功能和认证方式核对官方当前行为；需要变更的落实实现并测试；条件字段不能无条件附加 |
| 客户端名称、版本、入口、SDK 与运行时声明 | 分别记录官方样本和执行器现状；发现历史兼容声明时列明来源和差异，不静默改动 |
| 操作系统、架构、Shell、时区 | 区分容器自身信息与客户端提交的任务上下文；仅在接口确有需要时发送必要的真实信息，不以“对齐”为由替换客户正文 |
| 账号、会话、设备标识和凭据 | 按对应账号、会话及协议合法生成和隔离；不复制官方样本里的具体值，不写入脱敏对照文档 |

优先级只表示项目升级工作的检查顺序，不覆盖真实信息、凭据隔离和用户内容完整性要求。尚未验证的差异必须写明，不能以请求头相同推断环境相同或服务端识别结果相同。

## 每次升级的必做步骤

1. 核对 Anthropic 官方 release 与 npm 版本，固定版本号、平台、下载来源和摘要，不能把本机旧版本写成最新版。
2. 在隔离目录和闭网环境运行官方原包，记录实际版本、启动方式、认证方式和平台。使用虚构密钥与本地模拟服务，不使用生产账号，不替换已安装客户端。
3. 对比固定 CPA 源码默认、当前 Go 候选的实际出站请求、官方客户端样本。分别列请求头、system、messages、tools、metadata，记录每个字段的来源和位置变化。
4. 操作系统、架构依赖实际平台；会话、账号、设备标识及凭据依赖具体请求和账号。不得把一条样本的全部值固定复制到所有账号，也不把字段对齐当作不会被识别或不会被审查的证明。
5. 对功能协议字段评估兼容性；程序/SDK 标识、真实环境记录分别说明。遇到原版 CPA 无对应处理时列明差异，不自动拼装官方客户端身份或修改客户任务正文。
6. 完成修改后只测试受影响路径。官方订阅接口特有行为必须明确标为待真实账号验收；普通 API key 的闭网采样不能替代 OAuth 实测。

## 完成条件与记录格式

每次升级必须留存：核对日期、官方版本与来源、包摘要、启动方式、认证路径、平台、三方字段差异、具体修改、受影响测试结果及未验证项。

- 三方对照为：固定 CPA 原版、当前 Go 执行器、同类调用方式下的官方客户端。
- 交互模式与 `claude -p` 分开记录。`sdk-cli` 在本次 `-p` 样本中是调用入口标记，不能代表所有启动方式；不得为了统一标记而冒充另一种入口。
- 完成对照和受影响验证前，不得宣称“已与最新版完全兼容”。真实订阅路径未验证时，只能报告对应范围内的离线结果。
- 当前文档只增加升级规则；没有修改请求实现、冻结候选、生产配置或现有账号，也没有设定自动提醒。

## 历史核对：2026-11-24

- 官方最新 release 和 npm latest：2.1.331。
- 实测：Ubuntu Linux ARM64、非交互正常启动、隔离配置、假 API key、`--network none`，只请求容器内回环模拟接口。
- 结果：收到模拟 OK；User-Agent 为 `claude-cli/2.1.331 (external, sdk-cli)`；运行时声明 `node / v26.12.1`；SDK `0.128.0`；Linux / arm64；语言 js。
- 环境位置：Platform、Shell、OS Version 出现在 `messages.0.content.0.text`。旧版 2.1.186 样本的对应位置是 system，不能假定位置固定。
- 范围：没有真实 OAuth 授权或官方上游调用。本机原客户端仍为 2.1.186；CPA 和 Go 候选请求没有在本次被修改。

官方来源：https://github.com/anthropics/claude-code/releases/tag/v2.1.331 ，https://registry.npmjs.org/@anthropic-ai/claude-code/latest 。本次下载记录见 release-source.json，实际样本见 latest-client-capture.json，三方对照见 three-way-comparison.json。
```

## 记录 3：work/cpa-source-save-20261126-r2/AGENTS.md

```text
# Container runtime working rules

Read `UPGRADE_POLICY_CN.md` before changing or releasing the Go executor. Check the latest official Claude Code release at the time of an upgrade; distinguish protocol compatibility from client/runtime identity declarations. Do not copy identity, account, session, device identifiers or credentials from another client. Do not rewrite customer content to resemble a different environment.

Keep `source/` unchanged: it is verified against `source-inputs.json`. Use reviewed overlays in `src/` and update `overlay-inputs.json` when needed. Keep manually edited headers intact unless the user explicitly requests a compatible change. Never publish account data, generated keys, captures, production configurations or runtime state.

Run focused tests for affected behavior. A mock capture does not verify official subscription endpoints. Record real-account cases still awaiting validation. Production migration, deployment and real-account calls require their corresponding authorization; a source commit does not constitute deployment.

Use `build.py` as the unified build entrypoint. This snapshot is ARM64-only and relies on local Docker base images. See `README.md` and `RELEASE_STATUS_CN.md` for build and deployment limitations.

## Account request scope — 2026-11-26

Follow `ACCOUNT_REQUEST_INVENTORY_CN.md` for account request coverage and explicit field differences. OAuth, token refresh, profile, roles, usage and reset-card operations belong to this scope; do not leave undocumented exceptions. Distinguish existing behavior from implemented changes and from observed wire results.

Browser request handling stays unchanged for now. At the end of subsequent project replies, remind the user that browser login/verification/callback and browser header handling still need review, until explicitly canceled or accepted. Keep the one-hour task acceptance reminder too. These are conversational reminders, not scheduled automations.

The current candidate must not be published; existing accounts and NewAPI must remain untouched. Updating this inventory does not authorize changing header values or production behavior.

## Test scheduling — latest user instruction, 2026-11-26

Pause new test runs now; accumulate affected cases for the later consolidated test phase. Do not run tests after each individual edit or repeatedly ask to test each step. One local OAuth wire capture completed before this instruction arrived; preserve that result without rerunning it. Current OAuth restoration is in source only; the runtime image has not been rebuilt for it. No production or existing-account changes.

## Current authorization

User authorized consolidated isolated tests and local test-image packaging for this snapshot. Production, existing accounts, NewAPI and real-account calls remain excluded. Do not alter user runtime source to satisfy assertions.

## Latest instruction — 2026-11-26
Re-read user-edited source and compile only. Functional tests remain paused. No production deployment, real-account calls or NewAPI changes. Previous evidence does not validate this new revision.

## Source save authorization — 2026-11-26
User authorized committing and pushing this compile-only source snapshot to a separate branch. This does not authorize production deployment or real-account calls. Functional tests remain paused.

## Cooldown direction A — 2026-11-26
User selected preserving CPA routing/retry policy while repairing the worker/central bridge. Implement only in the candidate; compile without running functional tests, deploying, or calling real accounts. Keep reminding the user at the end of replies that reset-grant consumption remains pending; do not create a scheduled notification.

## Latest authorization — production preparation 2026-11-26
User now authorizes consolidated local tests, packaging and updating the local production release. Preserve account environments and credentials; no NewAPI changes. User will initiate real-account tests after readiness is reported. Capture Go account requests during an explicit test window; browser requests remain unchanged and outside this capture boundary. Only conservatively sanitized derived samples may enter samples/, never raw captures or keys.

## Latest authorization — single policy deployment
User authorized local production deployment preserving account environment/credentials and leaving NewAPI unchanged. Enable bounded header monitoring and before/after sampling; user initiates real requests. Do not make real model, manual refresh or reset-grant calls for readiness checks.
```

## 记录 4：work/cpa-source-save-20261126-r2/UPGRADE_POLICY_CN.md

```text
# Claude Code / CPA 升级前优先核对

来源：用户 2026-11-24 明确要求每次更新时优先考虑真实最新版 Claude Code 的请求字段。

每次 Go 执行器升级，官方最新版 Claude Code 的协议兼容性与隐私字段对照是首要升级检查项，必须先于请求参数改动和兼容验收结论。该规则是开发检查项，不是定时任务或自动改写请求的任务。

## 用户要求与实施范围

用户原始要求（2026-11-24）：

> go执行器传输的参数在更新go执行器时必须严格按照官方最新版claudecode传什么参数，执行器就传输什么参数，这个优先级最高

实施规则：以官方最新版为协议兼容基准，逐项核对字段名称、类型、位置、用途和生成条件；不将上述要求执行为无条件复制所有字段和值。这里明确保留用户原始要求与实施边界的区别，不能声称已完成全部参数的一比一复制。

| 字段类别 | 升级处理规则 |
| --- | --- |
| 模型、工具、流式等功能协议字段 | 对应同一接口、功能和认证方式核对官方当前行为；需要变更的落实实现并测试；条件字段不能无条件附加 |
| 客户端名称、版本、入口、SDK 与运行时声明 | 分别记录官方样本和执行器现状；发现历史兼容声明时列明来源和差异，不静默改动 |
| 操作系统、架构、Shell、时区 | 区分容器自身信息与客户端提交的任务上下文；仅在接口确有需要时发送必要的真实信息，不以“对齐”为由替换客户正文 |
| 账号、会话、设备标识和凭据 | 按对应账号、会话及协议合法生成和隔离；不复制官方样本里的具体值，不写入脱敏对照文档 |

优先级只表示项目升级工作的检查顺序，不覆盖真实信息、凭据隔离和用户内容完整性要求。尚未验证的差异必须写明，不能以请求头相同推断环境相同或服务端识别结果相同。

## 每次升级的必做步骤

1. 核对 Anthropic 官方 release 与 npm 版本，固定版本号、平台、下载来源和摘要，不能把本机旧版本写成最新版。
2. 在隔离目录和闭网环境运行官方原包，记录实际版本、启动方式、认证方式和平台。使用虚构密钥与本地模拟服务，不使用生产账号，不替换已安装客户端。
3. 对比固定 CPA 源码默认、当前 Go 候选的实际出站请求、官方客户端样本。分别列请求头、system、messages、tools、metadata，记录每个字段的来源和位置变化。
4. 操作系统、架构依赖实际平台；会话、账号、设备标识及凭据依赖具体请求和账号。不得把一条样本的全部值固定复制到所有账号，也不把字段对齐当作不会被识别或不会被审查的证明。
5. 对功能协议字段评估兼容性；程序/SDK 标识、真实环境记录分别说明。遇到原版 CPA 无对应处理时列明差异，不自动拼装官方客户端身份或修改客户任务正文。
6. 完成修改后只测试受影响路径。官方订阅接口特有行为必须明确标为待真实账号验收；普通 API key 的闭网采样不能替代 OAuth 实测。

## 完成条件与记录格式

每次升级必须留存：核对日期、官方版本与来源、包摘要、启动方式、认证路径、平台、三方字段差异、具体修改、受影响测试结果及未验证项。

- 三方对照为：固定 CPA 原版、当前 Go 执行器、同类调用方式下的官方客户端。
- 交互模式与 `claude -p` 分开记录。`sdk-cli` 在本次 `-p` 样本中是调用入口标记，不能代表所有启动方式；不得为了统一标记而冒充另一种入口。
- 完成对照和受影响验证前，不得宣称“已与最新版完全兼容”。真实订阅路径未验证时，只能报告对应范围内的离线结果。
- 当前文档只增加升级规则；没有修改请求实现、冻结候选、生产配置或现有账号，也没有设定自动提醒。

## 历史核对：2026-11-24

- 官方最新 release 和 npm latest：2.1.331。
- 实测：Ubuntu Linux ARM64、非交互正常启动、隔离配置、假 API key、`--network none`，只请求容器内回环模拟接口。
- 结果：收到模拟 OK；User-Agent 为 `claude-cli/2.1.331 (external, sdk-cli)`；运行时声明 `node / v26.12.1`；SDK `0.128.0`；Linux / arm64；语言 js。
- 环境位置：Platform、Shell、OS Version 出现在 `messages.0.content.0.text`。旧版 2.1.186 样本的对应位置是 system，不能假定位置固定。
- 范围：没有真实 OAuth 授权或官方上游调用。本机原客户端仍为 2.1.186；CPA 和 Go 候选请求没有在本次被修改。

官方来源：https://github.com/anthropics/claude-code/releases/tag/v2.1.331 ，https://registry.npmjs.org/@anthropic-ai/claude-code/latest 。本次下载记录见 release-source.json，实际样本见 latest-client-capture.json，三方对照见 three-way-comparison.json。
```

## 记录 5：work/cpa-source-save-20261126-r2/HEADER_POLICY_SINGLE_SOURCE_CN.md

```text
# 账号请求头单一策略源

## 范围与维护入口

唯一手工维护入口：`src/internal/accountheaders/policy.go` 内的 `PolicyJSON`。
`variables.client_version` 统一关联现有模型、资料、角色和用量请求头，以及 CPA 自动生成的正文 `cc_version`；令牌接口的库版本保持独立。
本次是结构迁移，保留用户既有 12 个模型头及账号接口最终值，没有升级身份/运行时声明。

| 请求 | 策略 | 最终设置者 |
| --- | --- | --- |
| 授权码交换、刷新 | token | 账号容器 Go providerTransport |
| profile | profile | 同上 |
| roles | roles | 同上 |
| usage（包含重置卡只读信息） | usage | 同上 |
| messages、count_tokens | model | 同上 |
| 浏览器登录、验证、回调前浏览器请求 | 不纳入 | 现有浏览器链路，未改动 |
| 重置卡消费 | 尚未实现 | 不声称已接入 |

OAuth 原生调用层只保留方法、地址、协议正文、凭据、解析和错误处理；容器构造函数明确将固定头的设置交给最终发送层。
独立运行、未接容器的 CPA OAuth 路径仍调用同一策略包。其原有 usage 预处理与容器最终处理的差异以 `native_usage` 显式列出，保留已有行为，不需另改版本字符串。
`set` 指定替换，`delete` 指定删除，`close` 明确 Go Request.Close；未管理字段沿用 CPA。
认证令牌、会话和请求标识按请求生成/保留，不进入固定策略；请求头策略不会修改客户正文、工具或模型回复。CPA 自身生成的 system billing 文本通过 `accountheaders.ClientVersion()` 读取同一版本；已有透传分支保留的客户 attribution 不强制重写。

## 用户要求的排查工具

请求头监控和脱敏导出是用户指定的排查工具，继续保留。
发送与监控解析同一个不可变策略。监控仍检查真实写出的头、缺失、重复和未知字段，不用源码推断代替观测。
构建时从该 Go 常量生成 `image/account_header_policy.json`，供 Python 导出器使用；构建会打包同一快照。
采样、审计和脱敏记录携带策略版本/摘要。历史采样没有摘要时明确留空，不冒充当前策略。
导出的安全边界单独保留：凭据、Cookie、会话/请求 ID、未知值与正文自由文本不能因发送策略新增字段而变成明文。
常规协议响应值仍由脱敏器的小范围安全清单控制；策略中的值按对应头名匹配，不做跨字段白名单。

## 验证与限制

对迁移前的源码做本地冻结副本，之后用同一虚构 A/B 测试采集两份编译程序的最终 HTTP 请求；独立固定断言保留，不能只用新策略验证新策略。
迁移测试覆盖 OAuth 真实调用方法和 Go 发送层，不以本地模拟证明官方订阅接口已验收。
构建继续校验冻结源码和用户 12 个手工模型头。浏览器、路由选择、重试、冷却与生产配置不在此次改动范围。
本轮只生成候选和离线证据，不发布生产、不调用真实账号、不改 NewAPI。

## 升级核对（2026-11-26）

核对官方 GitHub latest 与 npm latest：2.1.332。
来源：https://api.github.com/repos/anthropics/claude-code/releases/latest ，https://registry.npmjs.org/@anthropic-ai/claude-code/latest 。
本次沿用已采集的同版本官方 Linux ARM64 原包闭网虚构 OAuth 样本：`work/official-oauth-capture-20261126/official-oauth-final-wire.json`，不重复同版本测试。
官方账号接口样本与当前声明的 2.1.331 版本差异仍保留；本次不做官方身份或运行时同步。官方样本不是生产 OAuth 行为证明。
真实账号最终请求与官方订阅端行为仍待用户发起验证。

## 后续生产授权（2026-11-26）
用户已明确授权发布此版到本机生产，保留账号环境和凭据、不改 NewAPI；真实请求由用户发起。发布前补齐加密的覆盖前快照、分阶段脱敏对比和系统托管采集。授权不包括代发真实模型请求或重新授权账号。


## cc_version 同步修订

正常 billing 生成、两种签名兜底及两种旧 system 入口均读取统一策略版本，当前为 `2.1.331`。三位摘要仍由原算法根据文本和版本重新计算，签名及 payload 最终处理顺序不变。保留冻结 `source/`，通过 `src/` 和两份 overlay 映射接入。旧默认设备配置不再决定这些生成入口的 billing 版本。

本次修改源码及相关测试预期；不代表运行中容器已更新，未调用真实账号或部署生产。以补丁旁的 validation.log 为本次本地验证结果，历史证据不替代当前验证。
```

## 记录 6：work/cpa-source-save-20261126-r2/ACCOUNT_REQUEST_INVENTORY_CN.md

```text
# 账号请求实现清单与字段差异登记

更新：2026-11-26（Asia/Tokyo）。依据本轮工作区源码核查，不代表生产已部署或真实端点已验证。

## 当前约束与完成标准

- 范围是所有账号相关请求。OAuth 换令牌、刷新、资料和用量均在范围内，不能作为未说明的例外。
- 浏览器请求处理暂时维持原样：不解密 HTTPS、不覆盖网页请求头、不改登录和回调方式。后续项目回复结尾提醒检查此流程，直到用户明确取消或验收；不创建定时提醒。
- 本轮增加 usage 专用请求头覆盖；仅修改候选源码和后续测试预期。候选暂不发布，不操作现有账号，不调用真实上游，不改 NewAPI。
- 下表区分当前实现、尚待修订和缺失能力。模型/远端计数保留现有 12 项覆盖；OAuth 原生处理保留，只有 GET usage 按用户最新指定的五项规则在最终层覆盖（见下节）。这是按用途明确保留原生逻辑，不宣称全部账号请求头相同。
- 实现统一管理不自动授权修改身份声明、账号/会话标识或客户正文。未列明字段或端点必须先补登记，不得默默增加旁路。

## 请求清单

定位简称：W=`src/cmd/server/offline_worker_entry.go`；H=`src/cmd/server/offline_header_policy.go`；A=`source/internal/auth/claude/anthropic_auth.go`；R=`src/internal/auth/claude/container_account.go`；I=`src/cmd/server/offline_account_info.go`；N=`src/cmd/server/offline_network.go`。路径均相对本目录。

|操作|发起入口与实际发送者|目的地|最终头处理位置／当前规则|状态与缺口|
|---|---|---|---|---|
|登录、授权、验证码、网页子资源|中央启动远程桌面；账号容器 Chromium 发 HTTP 请求|授权页从 `https://claude.ai/oauth/authorize` 开始；后续资源/登录目标由网页决定|Chromium 自己生成头；测试候选 Go 网络模式只转发加密连接|按用户要求保持；网页实际全部目标与字段尚未完整采样，持续提醒检查|
|授权回调|账号容器 Chromium 跟随授权后的跳转|`http://localhost:54545/callback?code=…&state=…`|浏览器生成本地请求；容器 Go 回调服务接收并校验 state|已实现；不是 Anthropic 主动连接容器，不是公网请求，不套模型头|
|回调交给换令牌处理器|同容器 Go 回调等待程序|Unix socket 上的 `http://worker/auth/complete`|W `awaitBrowserCallback`，本地 JSON 请求|已实现；本地交接不发送上游、不经 SOCKS|
|首次换令牌|W `completeAuthorization` 调用 A；容器 Go 发送|POST `https://platform.claude.com/v1/oauth/token`|A `applyClaudeOAuthAxiosHeaders`／原生查询函数；W 最终层不覆盖|已接通代码；本轮恢复原生逻辑，模型覆盖不适用于此请求|
|刷新访问令牌|中央原生调度／手动刷新触发容器刷新；容器 Go 发送|POST 同一 `/v1/oauth/token`|同上|已接通代码；调用用途与首次授权不同，不能复用授权码正文；候选真实验证待授权|
|授权期间账号资料|A 的授权后资料补充流程；容器 Go 发送|GET `https://api.anthropic.com/api/oauth/profile`|同一 CPA 原生 OAuth 处理，最终层不覆盖|已实现；必须列入账号范围|
|授权期间角色资料|A 的授权后资料补充流程；容器 Go 发送|GET `https://api.anthropic.com/api/oauth/claude_cli/roles`|同一 CPA 原生 OAuth 处理，最终层不覆盖|已实现；不是刷新用量按钮固定查询的第三项|
|刷新用量：订阅资料|管理页 `account-update` → 中央 → 容器 `/auth/account-update`；I 并行调用 R，Go 发送|GET `/api/oauth/profile`|同一 CPA 原生 OAuth 处理，最终层不覆盖|已实现；与 usage 并行，失败项保留旧观测并标错|
|刷新用量：额度、重置卡读取|同上；Go 发送|GET `https://api.anthropic.com/api/oauth/usage?cedar_ember=1&skip_spend=1`|A 原生组装 → H usage 专用覆盖|只读查询与展示；此请求不消费卡；新头策略待集中验证，尚未构建部署|
|模型调用（普通／流式）|用户 → NewAPI → 中央 → 账号容器原生 CPA 执行逻辑|POST `https://api.anthropic.com/v1/messages`|CPA 原生组装 → W RoundTrip → H 模型 12 项覆盖|已接通代码；新 Go 网络路径尚未完成集中回归，不能宣称候选已验收|
|远端 Token 计数|同一账号容器执行逻辑|POST `https://api.anthropic.com/v1/messages/count_tokens`|同一模型 12 项覆盖|远端分支已接通；CPA 本地估算分支不发上游请求|
|模型回复附带额度观测|容器读取已有模型响应头，中央/NewAPI 读取快照|不产生新的上游请求|响应解析而非出站头覆盖|沿用 CPA 观测；不等于每次都取得完整订阅余额或重置卡状态|
|重置卡消费|计划由中央转交账号容器 Go；当前未提供可用消费动作|当前没有接通的容器消费端点，不编造 URL|未登记最终请求头规则|未实现；能力 `reset_grant=false`。确认、防重复消费、结果未知后的核对仍需开发和协议依据|
|创建前出口与时区检查|无账号数据盘的临时容器；候选同一 Go 二进制 `network-probe`|HTTPS `ipwho.is/?fields=ip,success,timezone.id`|N `probeHTTP` → H `applyNetworkCheckHeaders`|候选代码已写；不是携带订阅凭据的请求；新链路待集中验证|
|启动出口检查及固定时区核对|候选账号容器 Go `network-serve`，打开账号状态之前|`api.ipify.org/?format=json`；必要时 `www.cloudflare.com/cdn-cgi/trace`；时区查询 `ipwho.is`|同一网络检查规则|候选代码已写；无五分钟定时公网检查；不自动改固定时区|

本表列明应用显式发起的请求。浏览器子资源和 HTTP 重定向是否扩大最终目标范围，仍需分支检查与本地抓取，不以入口表代替全部实际出站证明。

## usage 专用覆盖（2026-11-26）

仅匹配 GET `https://api.anthropic.com/api/oauth/usage`，含现有查询参数的请求同样匹配；其他 OAuth 操作和模型覆盖保持当前候选的实现。

|请求头|最终策略|
|---|---|
|User-Agent|`claude-cli/2.1.331 (external, sdk-cli)`|
|Content-Type|`application/json`|
|Cache-Control|删除全部大小写变体，不发送空值占位|
|Connection|`keep-alive`，同时设置 `Request.Close=false`|
|anthropic-beta|`oauth-2025-04-20`|

Authorization、查询参数和正文不改。传输层仍为 `MaxIdleConnsPerHost=-1`，不保留空闲连接；上述头策略不代表已启用 TCP 连接复用。未改浏览器或冻结的 `source/`，已有 overlay 映射无需变更。

## 现有模型 12 项覆盖与 CPA 原生 OAuth 默认值差异

下表列原生默认值；usage 的最终值以上节专用覆盖为准。

“不新增”指 CPA 原生 OAuth 头函数没有设置该字段；不等于承诺整个调用链永远不出现该字段。

|字段|模型最终覆盖值|CPA 原生 OAuth 生成|差异性质与后续处理|
|---|---|---|---|
|User-Agent|`claude-cli/2.1.331 (external, sdk-cli)`|`axios/1.15.2`|按用户新指示恢复 CPA 原生值；control-recovery1 二次覆盖已移除，不声明等同官方 Claude Code|
|X-Stainless-OS|经过启动核验的持久平台基线|不新增|平台声明，不是 OAuth 授权参数；当前仅模型使用，缺口已登记|
|X-Stainless-Arch|经过启动核验的持久架构基线|不新增|同上；不能拿声明当作实际环境一致性证明|
|X-Stainless-Runtime|`node`|不新增|人工历史声明；Go 实际实现并不会变成 Node；不能称协议必填|
|X-Stainless-Runtime-Version|`v26.12.1`|不新增|人工历史声明；不能称协议必填|
|X-Stainless-Lang|`js`|不新增|人工历史声明；不能称协议必填|
|X-Stainless-Package-Version|`0.128.0`|不新增|人工历史声明；不能称协议必填|
|X-App|`cli`|不新增|客户端声明差异；是否需要由兼容性证据决定，不默认复制|
|Anthropic-Dangerous-Direct-Browser-Access|`true`|不新增|端点相关声明；不因存在于模型头就假定适用于换令牌|
|Anthropic-Version|`2023-06-01`|不新增|模型 API 版本；当前 OAuth 代码不使用。不能声称服务端禁止额外携带，亦不能无验证认定必需|
|Accept|`application/json`|`application/json, text/plain, */*`|响应协商差异；广泛接受列表是现有实现选择，未证明必须不同|
|Accept-Encoding|`gzip, deflate, br, zstd`|`gzip, compress, deflate, br`|压缩能力声明；必须与读取/解压能力匹配，统一前测试所有声明编码，不能仅改字符串|

## 必须单独登记的协议与关联字段

以下说明保留差异的用途，不把全部差异冒称官方强制。服务端是否接受某种替代值，需对应证据。

|字段／数据|当前来源与处理|保留不同值的理由／验证要求|
|---|---|---|
|Authorization|模型及资料/角色/用量使用选中账号的 Bearer token；首次换令牌、刷新请求由原生 OAuth 代码组装，当前不设置此头|认证必须绑定正确账号和操作，不能透传客户的 NewAPI/CPA 密钥，也不能用固定模板替代令牌；重置卡消费的认证待确认|
|Proxy-Authorization／SOCKS 用户名密码|绑定账号代理的连接认证，与上游 HTTP 认证分离|只给代理使用，不得添加到 Anthropic 请求头|
|Content-Type|后台 JSON 请求由 CPA 设置 `application/json`；浏览器暂保持自己的实际内容类型|必须描述真实编码；浏览器表单、资源请求不能统一假定 JSON。当前 OAuth GET 也设置 JSON 是现有实现，不称必需|
|Accept／Accept-Encoding|见上表；模型最终人工覆盖优先于 CPA 先前选择|需核对普通/流式响应与实际解压支持；当前流式也覆盖为模型常量，不能宣称已验证所有格式|
|Connection|CPA 原生 OAuth `close` 且 `r.Close=true`；usage 最终改为 `keep-alive` 且 `r.Close=false`；模型由 CPA 原生分支和 HTTP 传输层决定|连接生命周期策略，现有差异不属于账号身份要求；最终线上的结果需看实际传输，不能仅按 map 下结论|
|Host／TLS 服务名|由实际目标 URL 和连接决定|token 与模型/资料主机不同，必须与目标匹配；不能固定为一个主机名|
|Content-Length／Transfer-Encoding|由实际正文与 HTTP 传输方式计算|不能复制别的请求长度或强行统一传输分帧|
|Anthropic-Beta|CPA 原生依据请求能力、认证及配置组装；不在 12 项覆盖中|功能协议开关，不能固定成跨所有端点同一值；具体分支须捕获，仅 usage 最终规则固定为 `oauth-2025-04-20`，其余 OAuth 不主动新增|
|X-Claude-Code-Session-Id|CPA 原生会话逻辑，部分分支保留/生成；不在 12 项覆盖中|会话关联数据，不能固定为跨账号共用值；需检查账号和会话隔离，不能用其他账号样本值|
|X-Client-Request-Id|原生按配置、客户端类型决定生成/保留/删除|请求追踪数据，不能全局固定；记录实际来源与适用分支|
|X-Stainless-Retry-Count|原生按分支提供默认或保留；最终 12 项不覆盖|重试声明；不能把该声明当作实际已经重试次数的证明，按 CPA 逻辑核对|
|X-Stainless-Timeout|原生模型与 count_tokens 分支处理不同；最终 12 项不覆盖|请求头声明与程序超时是两回事；不能凭它证明一小时任务能够完成|
|X-Stainless-Async|原生识别到相应客户端且传入 async 时可设置|不是所有请求都有；需在条件分支中验证|
|X-Claude-Code-Agent-Id、X-Claude-Code-Parent-Agent-Id|原生部分分支保留输入|可能携带客户端代理/任务关联信息；当前 12 项不会清除；需逐项来源验证|
|X-Claude-Remote-Container-Id、X-Claude-Remote-Session-Id|原生部分分支保留输入|可能携带客户端环境关联信息；当前 12 项不会清除；不能声称上游只见容器自身信息|
|X-Client-App、X-Anthropic-Additional-Protection|原生部分分支保留输入|分别记录应用声明/保护字段来源，不能无依据删除或替换|
|X-Claude-Code-Request-Class、X-Claude-Code-Agent-Type、X-Claude-Code-Prev-Tool-Durations、X-Claude-Code-Compaction、X-Claude-Code-Context-Compacted|原生确认客户端后的分支可能保留|客户端任务状态；来源、触发条件与用途需分别在样本中记录，当前不属于 12 项覆盖|
|Cookie／Set-Cookie|模型转发边界过滤客户 Cookie；浏览器 Cookie 仍由原浏览器资料管理|不能将浏览器认证 Cookie 套用到模型或其他账号；浏览器本轮不改|
|code、state、code_verifier、redirect_uri|首次换令牌 JSON 正文／本地回调参数，由本次授权生成或配置|授权绑定/校验用途；不是请求头，不能当模板清洗或拿历史真实授权码重放|
|grant_type、refresh_token、client_id、scope|原生 OAuth 正文，首次授权与刷新分开|操作语义与授权客户端绑定；刷新令牌为账号私有数据，不得跨账号共用|
|cedar_ember、skip_spend|只读 usage 查询参数，当前均为 1|不是请求头；读取与消费分开，不把参数查询当作消费已实现|
|重置卡 grant_id／操作号／幂等字段|消费接口尚未接通|未知项明确保留空缺；不得假造服务端幂等承诺或自动重试消费|

CPA 的自定义头配置、协议转换和 payload 配置也可能影响输入；模型最终规则未覆盖的字段不是“自动全部透传”。上述原生条件分支来自代码审阅，尚未逐个实际采样，不代表当前真实账号全部携带。

## 后续实施与验收清单

1. 用本表作为唯一账号请求范围清单；新增端点/字段先登记发送者、目的地、来源、最终处理位置和证据。现有原生未处理的情况列为缺口，不默默自创行为。
2. 对非浏览器账号请求逐项审查功能字段和现存声明差异，形成明确覆盖/保留策略；不以“OAuth 特例”跳过说明，不因统一入口就宣称全部头相同。
3. 完成受影响代码后集中本地回归：首次授权、刷新、profile、roles、usage、普通/流式模型与远端计数；每项捕获实际最后发送的头、正文摘要、发送进程和返回结果。使用虚构 A/B，检查串号及请求体未被额外改写。
4. 重置卡消费单独完成协议依据、确认、持久化防重与未知结果处理；没完成前保持禁用，不能把展示/读取通过当作消费完成。
5. 浏览器处理暂不进入改造；后续回复持续提醒检查登录、验证码、回调及浏览器请求头。内存候选的真实网页复测也待用户授权，不碰现有账号。
6. 候选完整回归、目标 Linux 验证、真实订阅兼容性及一小时长任务仍有待验收；当前不发布。真实验证若获授权，沿用同一环境、仅一次授权，不自动重复登录。

## 状态更新

历史状态（本次 usage 修改前）：2026-11-26 用户新指示：OAuth 恢复 CPA 原生头处理；已移除测试源码中的 control-recovery1 覆盖，模型 12 项不变。原生模型兜底通过冻结源校验，未修改。受影响本地抓取与构建结果见 tests/OAUTH_NATIVE_RESTORE_CN.md。此前整套 native7 回归尚未完成，生产、现有账号与 NewAPI 不动。本清单优先于旧文档对“所有账号请求统一完成”的笼统表述。


### 最新候选：usage 五项请求头

按用户表格修改 H；同步修改已有测试的 usage 例外预期和健康检查策略版本。遵循当前暂停测试指示：本次未运行测试、未构建镜像、未调用真实账号、未部署；此前抓取结果仅证明此前版本，不能作为本次验证结果。

集中验收待办：

1. usage 的五项字段及 `Request.Close=false`；带／不带查询参数；Cache-Control 大小写变体均不存在。
2. 拒绝其他主机、方法和路径套用 usage 规则；真实发送抓取与响应解码核对。
3. 虚构 A/B 账号 Authorization 隔离、查询参数及正文完整；profile、roles、换令牌和刷新维持原生行为，模型 12 项维持不变。
4. 执行已同步预期的 egress、平台头及 OAuth 抓取用例；保留历史抓取证据。测试 HTTP 传输声明与实际连接生命周期的差异。
5. 普通／流式、远端计数、错误分支、目标 Linux、真实订阅兼容性及一小时长任务仍待验收；浏览器登录、验证、回调和请求头仍待检查。
```

## 记录 7：work/cpa-source-save-20261126-r2/tests/CURRENT_PLAN_CN.md

```text
> 2026-11-26 最新测试安排：用户要求暂停新增测试，留到后续集中执行。一轮 OAuth 本地抓取在指令到达前已结束，保留结果，不重复跑。恢复修改尚未重建运行镜像，不能说已更新部署。
>
> 2026-11-26 后续变更：OAuth 按用户指示恢复 CPA 原生处理，模型 12 项保持；原生模型兜底已校验未变。受影响验证见 [OAuth 恢复记录](OAUTH_NATIVE_RESTORE_CN.md)。候选不发布，现有账号不动。

> 2026-11-26 当前计划：以 [账号请求清单](../ACCOUNT_REQUEST_INVENTORY_CN.md) 为准。浏览器请求处理暂时保持原样，后续对话结尾提醒检查登录、验证码、回调与浏览器头处理；一小时长任务继续提醒。候选暂不发布，现有账号/NewAPI 不动。当前只有模型/远端计数套用 12 项覆盖，其他账号请求差异和重置卡消费缺口均已逐项登记；不能称全账号覆盖已完成。此次只改文档，没有测试或部署。
>
> 2026-11-25 历史更新：下述协议接入与 OS/架构基线已在 container-native4 开发并完成离线验收；当时生产未切换。详见 ../NEWAPI_CONTAINER_INTEGRATION_CN.md。下文保留最初核查记录，其中旧的“当前”“未完成”表述不作为 2026-11-26 状态依据。

# 当前范围与后续计划

更新：2026-11-25；本文件覆盖旧验收记录中相冲突的后续待办。依据用户最新要求。

## 已确认的范围调整

- 一小时长任务保留为待验收项。每轮开发结果的对话结尾提醒，不创建定时提醒或后台任务。不得把短请求通过当作一小时已验证。
- 异机备份恢复从计划移除，不再主动安排或反复要求目标。保留已有同机持久盘、加密备份与恢复能力，不删除备份或账户数据。
- 用户希望协议能力参照原版 CPA。核查：固定 CPA 8.1.1 接受 Claude Messages、OpenAI Chat Completions/Responses 等格式，由原版转换器转成 Claude Messages，回复按调用方格式转换。当前容器池只挂入 Messages/count_tokens；其他原版路由虽存在，没有接入容器池。不能称“当前已与原版多协议接入一致”。恢复方向是复用原版入口、转换与回复逻辑，保持一账号一容器，不退回宿主机执行。
- 仅在同协议链路可承诺上游消息字节不变；跨协议必须按原版转换结构/流事件，不能同时承诺 OpenAI 返回与 Anthropic 返回逐字节相同。模型回答内容不作清洗或改写。

## 本次核查的环境现状

已只读核对活动发布 mac-production3-control-1795611409 的相关源码，与当前仓库一致。

- X-Stainless-OS / X-Stainless-Arch：每次 applyProviderHeaders 调用 containerPlatformHeaders，通过 syscall.Uname 读取容器可见 OS 名和机器架构；不是首次读取后持久化。OS 名不包含内核版本。
- 创建环境时持久记录架构、/etc/os-release 摘要、浏览器/执行器摘要、时区和语言。启动/恢复时重新采集并比对，不一致会阻止启动；不是直接覆盖已存基线。
- 时区来自首次出口检查；随后使用固定配置，观察到变化提示但不自动改时区。系统语言配置固定。
- 浏览器资料持久保存；这不等于所有浏览器可观测属性和宿主 Linux 内核版本都已固定。运行清单没有纳入内核 release。
- 其余手动模型请求头仍来自代码常量，不是首次容器探测结果。本次未改这些字段，也未修改客户正文。

## 后续开发顺序

1. 将原版 CPA 多协议入口、转换、错误/流式处理接入同一容器账号池。复用原版实现，离线验证普通/工具/错误/流式，检查无宿主直连回退；明确 HTTP 与 WebSocket/compact 等路径各自范围，不概括为全协议已支持。
2. 对必要的、真实的 OS/架构字段增加账号环境持久基线读取；创建时记录，后续使用已核对基线；重启/本机恢复先重新检测实际环境，差异时明确拦截，不能用旧值掩盖实际平台改变。已录入账号应从现有可信基线迁移，不能重新授权或更换设备标识。
3. 用户明确允许真实终验后，首先留存指定请求的脱敏样本；沿用同一账号环境，只授权一次。保留一小时长任务提醒。

本文件仅记录核查和待开发事项。当前没有完成上述新增协议适配或首次采集固化改造，也未部署代码变更、调用生产模型或变更现有账号。
```

## 记录 8：work/cpa-source-save-20261126-r2/RELEASE_STATUS_CN.md

```text
> 当前源码候选：container-native4（未部署）。NewAPI 对接、多协议与 OS/架构基线见 [NEWAPI_CONTAINER_INTEGRATION_CN.md](NEWAPI_CONTAINER_INTEGRATION_CN.md)。本机生产仍为上一发布版本；以下旧阶段记录供追溯。

# 2026-11-25 源码交付状态

mac-production1 在 portable-capture1 上增加 Mac 生产配置检查、保留既有访问密钥和管理密码、内部控制认证、完整 launchd 切换与回滚。Go 执行器及手动请求头未改。

当前支持空账号首次切换；用户此前已授权删除失效账号，不再迁移旧订阅凭据。安装、回滚与验证边界见 MAC_RELEASE_CN.md。正式订阅授权和官方模型路径仍待新账号验证，全程一次授权。

源码通过 fylsan3/CLIProxyAPI 的 codex/portable-capture1-source 分支维护，main 未合并。发布包排除账号、生产配置、日志、原始请求、私钥、编译产物和 Docker 镜像；异机构建需准备 README 中注明的工具链和本地镜像。

下一步是确认已安装状态，录入新账号，优先核对实际出站字段，再验收真实模型回复、刷新和重启恢复，最后联调已有 NewAPI。Linux 不作为本机 Mac 发布的前提。
```

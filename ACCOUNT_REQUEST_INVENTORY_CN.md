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

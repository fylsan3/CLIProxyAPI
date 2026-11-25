# OAuth 恢复 CPA 原生处理：开发与待测记录

2026-11-26。测试版源码变更，不是发布记录。

## 已改源码

- offline_header_policy.go 移除 accountControlUA 和 OAuth 二次覆盖，保留原生 OAuth 客户端生成的请求头与连接策略。
- 模型的 12 项人工覆盖不变。CPA 原生模型兜底未被补丁替换，冻结源码校验通过 2615 个文件；继续保留原生行为。
- 更新相关当前测试预期和范围文档。冻结基线、原版 source、历史测试样例不进行全文替换。
- 修改前重新核对 GitHub/npm：官方版本均为 2.1.332；本轮不复制官方身份字段。版本证据在 ../client-version-audit-20261126/oauth-restore-release-check.json（相对本仓库父目录）。

## 指令到达前已经结束的一轮验证

tests/oauth_native_capture.py 编译真实 worker 发送层与原生 OAuth 实现，在 Linux ARM64 临时容器执行。Docker network=none，无账号盘；虚构凭据，仅回环 HTTPS 模拟上游。

- 7 次 OAuth 请求：首次换令牌及伴随 profile/roles、刷新令牌及伴随 profile、手动资料/usage 查询。
- 原生客户端直接发送与经过修改后 providerTransport 的请求头、正文摘要、目标路径和关闭连接状态相同。
- OAuth 捕获 UA 为 axios/1.15.2，不含 control-recovery1。
- 额外捕获原生模型兜底 CLIProxyAPI/8.1.1（测试构建版本设为 8.1.1），以及最终模型/计数请求；12 项覆盖与模型请求体保持。
- 原始本地结果：evidence/oauth-native-final-wire.json；日志：evidence/oauth-native-test.txt。

这不验证真实订阅接口、中央调度、容器完整启动，也不构成整套 native7 验收。

## 最新用户安排：暂停新增测试

上述本地抓取结束后，用户要求“先别测试了，等会一起测试”。自此不再启动新测试，保留已完成结果。

后续集中阶段再做：统一构建测试执行器和镜像、受影响的现有测试、原生 OAuth 返回错误及连接行为回归、测试容器完整链路核对。已有通过的本地案例只在代码再次变化或新问题需要时重跑。

当前 image/worker、镜像和发布清单尚未为此次 OAuth 恢复更新；不可用旧镜像报告新代码生效。未部署，现有账号、浏览器与 NewAPI 未操作。

持续提醒：浏览器登录/验证码/回调/请求头流程仍待检查；一小时长任务仍待验收。

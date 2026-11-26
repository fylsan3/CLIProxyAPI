# 单一请求头策略验收（2026-11-26）

结论：测试候选已完成集中验证；没有发布生产，没有调用真实订阅账号，没有改 NewAPI。

| 项目 | 结果 |
| --- | --- |
| Mac ARM64、Linux ARM64 构建 | 通过 |
| 虚构 A/B 迁移前后最终请求 | 20 组对照通过，头、正文 SHA256、Request.Close 一致 |
| 授权码交换、刷新、profile、roles、usage | 原生 OAuth 方法与最终 Go transport 实际闭网 HTTP 采集通过 |
| 模型请求、count_tokens、原生兜底 | 最终值一致，12 个手工模型字段保持 |
| 容器 OS/架构与恢复核验 | 通过 |
| 请求头监控 | 正常无误报；冲突/重复 UA、未知字段、roles 不允许字段可检出 |
| 加密原始归档及本地重放 | 头/正文/响应一致；篡改、截断被拒绝 |
| 脱敏导出 | 4 项安全测试通过；凭据、Cookie、正文、未知值不明文导出 |
| 中央→虚构 A/B→模拟上游→采样导出 | 通过；采集账号请求、A/B 并发、收集器不额外请求上游 |
| 非容器 OAuth 原有行为 | 3 项已有独立固定断言通过 |

对照仅规范化原生兜底测试服务器随机分配的 `127.0.0.1:端口`；官方域名、HTTP 请求头和值、方法、路径和正文摘要严格比较。
测试中旧断言要求最终层不处理 OAuth，已按本次职责迁移调整，并保留独立固定值断言。
新增 overlay 包的虚拟目录不支持 Go vet 的工作目录切换，编译采样运行器因此关闭其隐式 vet；共享包在有真实目录的临时模块中接受常规 vet 与测试，没有修改冻结 source/。

协议/身份声明：本次没有把声明同步到最新官方版本。现有 2.1.331、node 等手工声明保留，实际程序仍为 Go。官方 2.1.332 历史闭网样本复用，官方实时版本已重新核对。
请求头策略只管理请求头；原生 CPA 已有正文转换行为未更改，不能把本次结果解读为整个 CPA 对正文从不处理。

证据（本地 evidence/，不包含真实账号）：
- header-policy-acceptance.json：最终汇总。
- header-policy-migration.json：20 组比较。
- header-migration-before/after-A/B.json：虚构请求完整最终头。
- header-policy-checks.log、header-policy-platform.log、header-policy-native-oauth.log。
- header-policy-export.log、capture-chain.json：导出与全链路。

下一步：评审候选差异后单独发布，再在用户发起的真实测试窗口检查官方订阅端。浏览器登录/验证/回调、重置卡消费和一小时长任务仍单列待办；不把此次离线通过写成全部生产验收。

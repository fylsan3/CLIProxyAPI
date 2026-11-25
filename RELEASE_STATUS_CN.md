> 当前候选：mac-production3 / accounts-ui12。账号管理整合范围和待真实验证项目见 [ACCOUNT_MANAGEMENT_RELEASE_CN.md](ACCOUNT_MANAGEMENT_RELEASE_CN.md)。以下旧阶段记录保留供追溯。

# 2026-11-25 源码交付状态

mac-production1 在 portable-capture1 上增加 Mac 生产配置检查、保留既有访问密钥和管理密码、内部控制认证、完整 launchd 切换与回滚。Go 执行器及手动请求头未改。

当前支持空账号首次切换；用户此前已授权删除失效账号，不再迁移旧订阅凭据。安装、回滚与验证边界见 MAC_RELEASE_CN.md。正式订阅授权和官方模型路径仍待新账号验证，全程一次授权。

源码通过 fylsan3/CLIProxyAPI 的 codex/portable-capture1-source 分支维护，main 未合并。发布包排除账号、生产配置、日志、原始请求、私钥、编译产物和 Docker 镜像；异机构建需准备 README 中注明的工具链和本地镜像。

下一步是确认已安装状态，录入新账号，优先核对实际出站字段，再验收真实模型回复、刷新和重启恢复，最后联调已有 NewAPI。Linux 不作为本机 Mac 发布的前提。

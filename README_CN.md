# mac-production1

基于 portable-capture1 增加 Mac 空账号生产启动、配置保留、整体切换与回滚。保留 Go 执行器、原生账号调度及已有手动请求头。

- Mac 生产安装与回滚：见 MAC_RELEASE_CN.md。
- 独立测试：launch.py 默认仍按隔离测试规则启动；--production 才允许经过检查的生产配置。--ephemeral 只供一次性虚构账号测试，生产模式禁止使用。
- Linux：见 linux/README_CN.md；当前仅 ARM64，目标机器 systemd 启动另行验收。
- 单次采样：见 采样与重放说明.md，不会自动开启生产正文日志。
- 统一构建：build.py，避免分别构建组件造成混装。

源码在 fylsan3/CLIProxyAPI 的独立分支维护，不覆盖 main。源码、已安装版本、真实订阅验收分别记录；没有真实账号验证时不能宣称官方服务已接通。

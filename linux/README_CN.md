# Linux 测试部署包

本目录把中央 CPA 和账号控制器拆为两个 systemd 服务。中央服务以 cpa-central 运行，只能通过 /run/cpa-control/model.sock 派单；控制器以 cpa-broker 运行，有 Docker 权限。账号仍各自在自己的 Ubuntu 容器中运行，浏览器按需打开。Docker 管理权限等价于主机高权限，不能授予中央用户。

当前交付只包含 Mac ARM64 与 Linux ARM64 程序及 ARM64 镜像。Linux x86_64 不是已验证目标，安装时会拒绝启动；需要另建对应架构镜像与程序。要求 systemd、Python 3、Docker、libseccomp.so.2，以及支持 Landlock 网络限制的内核（ABI >= 4）；能力不足就拒绝启动，不退回直连。

## 打包与安装

在新目标机器，把完整的不可变版本目录放到 /opt/cpa-portable，保持目录可读可执行，程序文件可执行。先将 image.json 列出的镜像导入目标 Docker，镜像 ID 必须一致。管理配置放在 /etc/cpa-test/network.json，凭据不要放进版本目录。

生成安装包（不会启动服务）：

```sh
python3 -B /opt/cpa-portable/linux/deploy.py --app /opt/cpa-portable --output /tmp/cpa-install --network-config /etc/cpa-test/network.json
```

只有明确安排目标部署时，才由管理员执行以下安装步骤；本机没有执行：

```sh
sudo python3 -B /tmp/cpa-install/install.py
sudo systemctl enable --now cpa-central.service
```

安装器拒绝覆盖已有 /var/lib/cpa-central、/var/lib/cpa-broker 或同名服务。新建的备份目录为 /var/lib/cpa-broker/backups；这是同机备份，不能作为主机损坏后的异机备份。独立盘挂载须由目标管理员在启动服务前完成，RequiresMountsFor 会等待配置的挂载。

首次只监听 127.0.0.1:8318；管理页为 /accounts.html，管理密钥保存在 /var/lib/cpa-central/client-key。远程访问可通过受控 SSH 隧道；没有自动开放公网或修改 NewAPI。服务的启停、日志查看使用 systemctl / journalctl。

服务使用 Wants/After 配合启动前检查和失败重试，避免控制器暂时退出后把中央服务永久停住；服务仍在运行时，由原有派单通道报告控制器不可用。目标机器需验证 Docker 重启和 systemd 恢复顺序。

## 隔离措施

- 中央用户与控制器使用不同 UID；中央用户不能读取控制器私有目录，也不能连接 Docker socket。
- 中央程序由 network_guard.py 启动。Landlock 阻止它主动建立 TCP 连接，seccomp 阻止创建数据报和原始套接字。现有客户端连接的回复及内部 Unix 流通道仍可使用。
- 账号容器的网络约束、启动检查、凭据恢复仍沿用已有控制器逻辑。
- 服务停止等待上限设为 3700 秒；这不是“停止时必定保留所有在途请求”的承诺，程序自己的关闭行为仍适用。运行中的模型请求没有在这次改动中增加读取超时。

## 验证边界

本机验证的是 Linux 容器内实际中央二进制、降权、网络限制和 Unix 派单。systemd 真正开机启动、目标 Docker/挂载盘、远程浏览器、跨机器恢复仍须在目标机器验收。容器内部测试不能替代这些验收。本版本未部署生产、未使用真实订阅号。

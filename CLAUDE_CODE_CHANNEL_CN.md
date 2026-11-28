# Claude Code 2.1.331 容器通道

## 本次目标与范围

在 `claude` 分支给 Ubuntu 账号容器安装固定的官方 Claude Code 2.1.331，新增管理终端与一句话 API。CLI 自己发起模型请求；本轮改为复用 Go 授权，由 Go 独自刷新。原 Go 执行器与手工请求头参数保留；此通道不套用 Go 的请求头覆盖。

当前为隔离候选，未部署生产、未使用现有账号。精确版本以 `claude-code-lock.json` 的二进制散列核对，不称为最新版。

## 使用流程（2026-11-28 更新为共享 Go 授权）

1. 在账号卡片完成原有 Go 授权；两条通道共用这份账号授权，不再单独登录 CLI。
2. 点击卡片 **Claude Code → 认证状态**，查看是否已读取 Go 的有效凭据。
3. 点击“启动 Claude Code”才开启交互终端，也可由专门程序通过下面的独立 API 调用。仅打开状态弹窗不启动 CLI。“收起”保留终端进程，“关闭终端”结束进程且不登出 Go；使用 API 前先关闭终端。
4. Go 独自刷新凭据，每次新启动 CLI 读取最新访问令牌。主调用链与新程序调用链分开。

详细认证归属、有效期和剩余限制见 `CLAUDE_CODE_SHARED_AUTH_CN.md`。前一阶段的独立 CLI 登录入口已撤下。浏览器继续用于原账号授权及人工验证。

## API

地址：`POST /v1/claude-code/messages`，使用 CPA 正常 API 密钥校验，不使用管理密钥作为特殊绕过方式。

```bash
curl "$CPA_URL/v1/claude-code/messages" \
  -H "Authorization: Bearer $CPA_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"account":"test-01","prompt":"请只回复 OK"}'
```

`account` 是该卡片绑定的内部账号标识，在终端弹窗中显示；`prompt` 必填，最多 64 KiB；`model` 可选，省略时沿用 CLI 选择。每次 API 调用是独立会话，不自动续接前一条历史。

成功返回包装结构：

```json
{
  "id": "任务编号",
  "state": "succeeded",
  "result": {"type": "result", "is_error": false, "result": "OK"},
  "exit_code": 0,
  "error": null,
  "account": "test-01",
  "container": "容器短编号"
}
```

`result` 保留官方 CLI 最终结果事件，包括其实际报告的用量字段。示例省略了可选字段。正文文本位于 `result.result`。这是等待完成后返回的 JSON 接口，尚不是流式输出接口，也不是 Anthropic `/v1/messages` 协议；现有 `/v1/messages` 仍走原执行通道。没有改变 NewAPI。

此“一句话”接口关闭文件、Shell 等工具，不允许调用者传入命令、环境变量或任意 CLI 参数。任务上限两小时；客户端提前断开会取消该任务。管理终端运行正常交互 CLI，权限提示由登录的管理员自行确认。

## 登录资料、网络和环境

- 官方二进制：`/opt/claude-code/claude`。
- CLI 私有配置/工作目录：`/state/claude-code/home`、`config`、`workspace`，重启保留。共享 OAuth 原件仍由 Go 保存在 `/state/native-auth.json`。
- 新增本地 Python 服务负责进程、PTY 和不解密的 CONNECT 转发；CPA 中央负责 API 鉴权和账号绑定，模型请求由真实 CLI 发出。
- CLI HTTPS → 容器本地 CONNECT → 原账号 SOCKS 通道。域名交给 SOCKS 解析；不会在代理故障后退回宿主机直连。浏览器继续沿用原容器浏览器的 SOCKS 配置。
- 关闭自动升级以保持 2.1.331。正常启动时仅提供本账号 Go 的访问令牌；不向 CLI 提供刷新令牌。
- 共享认证仍沿用原 Go 凭据保存与备份机制；没有创建独立 CLI 刷新令牌副本。

## 构建与验证

```bash
CPA_BUILD_TOOLS=/path/to/go-tools python3 -B build.py \
  --claude-code-only \
  --claude-binary /path/to/verified/claude-linux-arm64 \
  --runtime-base sha256:已核对的本地运行镜像
```

构建同时核对原三组参数联动准则。输出到 `evidence/claude-code-build/`：Mac/Linux ARM64 中央程序、镜像清单，以及 `package/` 独立候选运行目录。不会覆盖仓库根目录原发布清单或切换生产。构建报告核对镜像中原 Go worker 的散列，保证未被本次替换。

离线测试使用真实 CLI、虚构 A/B 和 `--network none` 容器，模拟上游只位于容器回环地址。测试证书与测试密钥不进入正式候选镜像。结果见同目录 `test-report.json` 和 `ui-test.log`。

还需真实账号验证：现有 Go 授权被 CLI 接受、真实模型响应、轮换后新调用及长任务的到期行为。离线结果不能替代上述验证。Linux ARM64 已编译；实际 Linux 宿主机服务部署和 x86_64 镜像不在本轮实测范围。

按需运行、异常清理和重启集中验收见 `CLAUDE_CODE_LIFECYCLE_CN.md`。API 结束立即退出 CLI；容器空闲仅保留控制服务和原 Go 进程。

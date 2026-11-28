# 专门程序调用 Claude Code API

本示例对应 `claude` 分支候选，不代表已部署生产。原 NewAPI → CPA → Go 链路不变。本轮只提交源码和示例，不调用账号。

## 准备

- 测试候选提供 `POST /v1/claude-code/messages`。
- 使用 CPA 普通 API 密钥，**不是管理密钥**。示例从环境变量读取，不把密钥写入源码。
- `account` 填管理页 Claude Code 弹窗中显示的内部账号标识，不是显示名称或邮箱。`a` 仅为虚构账号示例；目标必须已注册且对应容器可用。
- 同账号手动终端开启时先点“关闭终端”；“收起”不会停止它。
- 示例需要 Python 3.9+，仅用标准库。将 `CPA_URL` 设为隔离测试候选的地址，不要直接填生产地址。

```bash
export CPA_URL='http://127.0.0.1:测试端口'
# 设置 CPA_API_KEY 为你自己的测试 API 密钥；不要把真实密钥提交到仓库。
python3 examples/claude_code_client.py --account a --message '请只回复 OK'
```

`model` 可选；不填由 CLI 选择。选择具体模型时增加 `--model '你的可用模型名称'`。

## 程序内指定账号、发送消息、取得回复

```python
import os
from examples.claude_code_client import ClaudeCall, APIError

call = ClaudeCall(
    base_url=os.environ['CPA_URL'],
    api_key=os.environ['CPA_API_KEY'],
    account='a',
    prompt='请只回复 OK',
    # model='你的可用模型名称',  # 可选
)
try:
    receipt = call.result()         # 等待这一条调用完成
    print(receipt['account'])       # 实际绑定账号
    print(receipt.get('container')) # 对应容器回执
    print(receipt['state'])         # succeeded
    print(receipt['result']['result'])  # 模型文本
    print(receipt['result'].get('usage'))  # CLI 实际上报的用量，可能没有
except APIError as error:
    print(error.status, error.response)
```

脚本打印完整 JSON，保留 CLI 的 `result` 事件。`id` 是任务编号，`credential_revision` 是启动时读取的 Go 凭据修订；均不是访问令牌。当前接口不是流式，也不是 Anthropic `/v1/messages` 格式；每次为独立会话，API 路径关闭文件/Shell 等工具。

## 取消任务

**当前公开 API 通过关闭本次 HTTP 连接取消，不提供按任务编号取消的公开接口。** `id` 随最终回复到达，不能用它轮询正在运行的调用。内部管理 RPC 有取消操作，但本示例不暴露管理密钥，也不把它冒称为普通 API。

```python
import os
import threading
from concurrent.futures import CancelledError
from examples.claude_code_client import ClaudeCall

call = ClaudeCall(os.environ['CPA_URL'], os.environ['CPA_API_KEY'], 'a', '待取消的测试消息')
# 实际程序可以在用户点击“停止”时调用 call.cancel()。
# 这里用计时器演示；如果提前完成，cancel() 返回 False。
timer = threading.Timer(3, call.cancel)
timer.start()
try:
    receipt = call.result()
    print(receipt['result']['result'])
except CancelledError:
    print('已关闭连接，请求取消；服务器清理可能仍在进行。')
finally:
    timer.cancel()
```

命令行也支持 Ctrl+C，或：

```bash
python3 examples/claude_code_client.py --account a --message '待取消的测试消息' --cancel-after 3
```

取消说明：

- 中央服务收到客户端断开后，经控制器通知容器停止并清理。清理完成后允许新任务；取消不能撤销已经执行的上游请求或已经发生的用量。
- `cancel()` 返回 True 表示本地发起了取消，不代表收到服务器清理完成确认。结果已经完成时返回 False；完成与取消存在正常竞态。
- 中间反向代理必须把客户端断开传播给 CPA。直连测试入口已验收；其他代理若继续保持与 CPA 的连接，取消不能保证及时到达。
- `call.result(timeout=...)` 只是本地等待期限；超时不会自动取消，需要显式 `call.cancel()`。示例 HTTP 超时为 7500 秒，高于服务两小时任务上限，没有短输出空闲超时。
- 网络错误不自动重试，避免不确定任务被重复执行。

## 常见响应

| 情况 | 响应/处理 |
|---|---|
| 正常结束 | HTTP 200；`state=succeeded`；文本在 `result.result` |
| 没有有效 API 密钥 | HTTP 401 |
| 请求字段或账号标识非法 | HTTP 400 |
| 账号 CLI 忙、终端未关闭 | 通常 HTTP 409；查看 `error` |
| 访问令牌过期 | HTTP 409；`waiting_for_go_refresh`，由 Go 处理，不在客户端刷新 |
| CLI 执行失败 | HTTP 502；查看完整任务回执 |
| 容器/控制服务不可用 | HTTP 503 |
| 客户端主动断开 | 客户端不再接收响应；管理页可查看运行状态 |

## 示例验证与后续

`tests/claude_code_client_test.py` 仅通过本地模拟 HTTP 验证指定账号/消息/模型、返回解析、错误保留和关闭连接取消，不连接真实账号。服务端生命周期证据见 `CLAUDE_CODE_LIFECYCLE_CN.md`。

下一步先对接隔离入口。若需要“立即返回任务编号 → 轮询状态 → 按编号取消并确认完成”，应另外开发异步任务 API；当前示例不承诺已有该功能。真实订阅兼容、一小时跨令牌到期、浏览器授权/验证/回调及重置卡仍为后续检查项。

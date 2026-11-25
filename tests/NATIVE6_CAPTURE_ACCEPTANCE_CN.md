# 完整 HTTP 采样修复验收

2026-11-25。未调用真实账号。

- 最终 Go HTTP 发送层实际请求头与模拟服务接收头对比通过，包括库补充字段、多值头、认证字段。
- 加密原件保留认证字段；目录与文件权限验证、并发检查通过，样本截断及篡改被拒绝。
- GET 空正文、POST 正文、未知长度分块上传、压缩回复、403、流式数据与响应 trailers 通过。
- 中断、取消及存储失败不标记为完整，不改业务回复。
- 两个虚构账号经中央 CPA 的实际链路，重放 6 次资料查询及 2 次模型请求，逐项核对请求与回复。
- 旧真实刷新仅有过滤快照，历史完整请求不可恢复。真实新样本等用户下次操作产生。

```json
{
  "real_accounts_used": false,
  "published": false,
  "browser_interaction_tested": false,
  "cases": {
    "reset_grants_read_sanitized_no_consume": true,
    "system_text_retained_nonstream_and_stream": true,
    "newapi_reads_central_only": true,
    "complete_encrypted_control_and_model_http_replay": true,
    "newapi_actual_cpa_management_integration": true
  },
  "archive_replay": [
    {
      "kind": "marked-model-request",
      "method": "POST",
      "status": 200,
      "request_header_names": [
        "accept",
        "accept-encoding",
        "anthropic-beta",
        "anthropic-dangerous-direct-browser-access",
        "anthropic-version",
        "authorization",
        "connection",
        "content-length",
        "content-type",
        "host",
        "user-agent",
        "x-app",
        "x-claude-code-session-id",
        "x-client-request-id",
        "x-stainless-arch",
        "x-stainless-lang",
        "x-stainless-os",
        "x-stainless-package-version",
        "x-stainless-retry-count",
        "x-stainless-runtime",
        "x-stainless-runtime-version",
        "x-stainless-timeout"
      ],
      "replay": {
        "request_method_match": true,
        "request_path_query_match": true,
        "request_headers_match": true,
        "request_body_match": true,
        "request_trailers_match": true,
        "response_status_match": true,
        "response_headers_match": true,
        "response_body_match": true,
        "target": "self_created_loopback_fixture",
        "real_provider_contacted": false,
        "original_credentials_sent_to_provider": false
      }
    },
    {
      "kind": "account-update",
      "method": "GET",
      "status": 200,
      "request_header_names": [
        "accept",
        "accept-encoding",
        "authorization",
        "cache-control",
        "connection",
        "content-type",
        "host",
        "user-agent"
      ],
      "replay": {
        "request_method_match": true,
        "request_path_query_match": true,
        "request_headers_match": true,
        "request_body_match": true,
        "request_trailers_match": true,
        "response_status_match": true,
        "response_headers_match": true,
        "response_body_match": true,
        "target": "self_created_loopback_fixture",
        "real_provider_contacted": false,
        "original_credentials_sent_to_provider": false
      }
    },
    {
      "kind": "account-update",
      "method": "GET",
      "status": 200,
      "request_header_names": [
        "accept",
        "accept-encoding",
        "authorization",
        "cache-control",
        "connection",
        "content-type",
        "host",
        "user-agent"
      ],
      "replay": {
        "request_method_match": true,
        "request_path_query_match": true,
        "request_headers_match": true,
        "request_body_match": true,
        "request_trailers_match": true,
        "response_status_match": true,
        "response_headers_match": true,
        "response_body_match": true,
        "target": "self_created_loopback_fixture",
        "real_provider_contacted": false,
        "original_credentials_sent_to_provider": false
      }
    },
    {
      "kind": "account-update",
      "method": "GET",
      "status": 200,
      "request_header_names": [
        "accept",
        "accept-encoding",
        "authorization",
        "cache-control",
        "connection",
        "content-type",
        "host",
        "user-agent"
      ],
      "replay": {
        "request_method_match": true,
        "request_path_query_match": true,
        "request_headers_match": true,
        "request_body_match": true,
        "request_trailers_match": true,
        "response_status_match": true,
        "response_headers_match": true,
        "response_body_match": true,
        "target": "self_created_loopback_fixture",
        "real_provider_contacted": false,
        "original_credentials_sent_to_provider": false
      }
    },
    {
      "kind": "account-update",
      "method": "GET",
      "status": 200,
      "request_header_names": [
        "accept",
        "accept-encoding",
        "authorization",
        "cache-control",
        "connection",
        "content-type",
        "host",
        "user-agent"
      ],
      "replay": {
        "request_method_match": true,
        "request_path_query_match": true,
        "request_headers_match": true,
        "request_body_match": true,
        "request_trailers_match": true,
        "response_status_match": true,
        "response_headers_match": true,
        "response_body_match": true,
        "target": "self_created_loopback_fixture",
        "real_provider_contacted": false,
        "original_credentials_sent_to_provider": false
      }
    },
    {
      "kind": "account-update",
      "method": "GET",
      "status": 200,
      "request_header_names": [
        "accept",
        "accept-encoding",
        "authorization",
        "cache-control",
        "connection",
        "content-type",
        "host",
        "user-agent"
      ],
      "replay": {
        "request_method_match": true,
        "request_path_query_match": true,
        "request_headers_match": true,
        "request_body_match": true,
        "request_trailers_match": true,
        "response_status_match": true,
        "response_headers_match": true,
        "response_body_match": true,
        "target": "self_created_loopback_fixture",
        "real_provider_contacted": false,
        "original_credentials_sent_to_provider": false
      }
    },
    {
      "kind": "account-update",
      "method": "GET",
      "status": 403,
      "request_header_names": [
        "accept",
        "accept-encoding",
        "authorization",
        "cache-control",
        "connection",
        "content-type",
        "host",
        "user-agent"
      ],
      "replay": {
        "request_method_match": true,
        "request_path_query_match": true,
        "request_headers_match": true,
        "request_body_match": true,
        "request_trailers_match": true,
        "response_status_match": true,
        "response_headers_match": true,
        "response_body_match": true,
        "target": "self_created_loopback_fixture",
        "real_provider_contacted": false,
        "original_credentials_sent_to_provider": false
      }
    },
    {
      "kind": "marked-model-request",
      "method": "POST",
      "status": 200,
      "request_header_names": [
        "accept",
        "accept-encoding",
        "anthropic-beta",
        "anthropic-dangerous-direct-browser-access",
        "anthropic-version",
        "authorization",
        "connection",
        "content-length",
        "content-type",
        "host",
        "user-agent",
        "x-app",
        "x-claude-code-session-id",
        "x-client-request-id",
        "x-stainless-arch",
        "x-stainless-lang",
        "x-stainless-os",
        "x-stainless-package-version",
        "x-stainless-retry-count",
        "x-stainless-runtime",
        "x-stainless-runtime-version",
        "x-stainless-timeout"
      ],
      "replay": {
        "request_method_match": true,
        "request_path_query_match": true,
        "request_headers_match": true,
        "request_body_match": true,
        "request_trailers_match": true,
        "response_status_match": true,
        "response_headers_match": true,
        "response_body_match": true,
        "target": "self_created_loopback_fixture",
        "real_provider_contacted": false,
        "original_credentials_sent_to_provider": false
      }
    }
  ],
  "test_resources_removed": true
}
```

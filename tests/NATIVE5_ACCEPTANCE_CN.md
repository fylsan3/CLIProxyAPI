# container-native5 验收记录

2026-11-25。只回归本次受影响链路。

- Go 与中央双平台构建通过；NewAPI 相关后端测试通过；前端 6 项重置卡测试、类型检查、修改文件 lint 与生产构建通过。
- 虚构 A/B 迁移与回滚通过；打开的浏览器先正常关闭，再复制资料；升级后原授权可继续调用模拟模型。
- 真实账号仅迁移、备份与健康读取，没有重新授权/刷新资料/调用模型。
- 离线浏览器测试两个容量均可完成，未稳定复现实际 SIGTRAP；空间上限调整与脱敏诊断已部署，真实 claude.ai 页面由用户复测。
- 历史额度只找到过滤快照，已另存本地且未加入仓库。不是完整 HTTP 抓包。
- 重置卡消费仅完成设计，仍未开放；真实读取结构及官方幂等语义未验证。

```json
{
  "quota-browser.json": {
    "real_accounts_used": false,
    "published": false,
    "browser_interaction_tested": false,
    "cases": {
      "reset_grants_read_sanitized_no_consume": true,
      "system_text_retained_nonstream_and_stream": true,
      "newapi_reads_central_only": true,
      "newapi_actual_cpa_management_integration": true
    },
    "test_resources_removed": true
  },
  "native5-production-verification.json": {
    "deployed": true,
    "release": "container-native5-1795616298",
    "configuration_unchanged": true,
    "account_files_unchanged": true,
    "environment_id_unchanged": true,
    "platform_browser_timezone_unchanged": true,
    "hostname_unchanged": true,
    "old_container_stopped": true,
    "old_volumes_retained": true,
    "new_container_running": true,
    "temporary_storage": "rw,nosuid,nodev,size=512m,mode=1777",
    "browser_open": false,
    "management_http": 200,
    "accounts_ready": [
      true
    ],
    "real_model_requests_sent": 0,
    "authorization_started": false,
    "manual_refresh_started": false
  },
  "browser-render-regression.json": {
    "192m": {
      "steps": [
        "html",
        "wasm",
        "canvas",
        "indexeddb",
        "cache",
        "opfs",
        "done"
      ],
      "done": true,
      "diagnostic": []
    },
    "512m": {
      "steps": [
        "html",
        "wasm",
        "canvas",
        "indexeddb",
        "cache",
        "opfs",
        "done"
      ],
      "done": true,
      "diagnostic": []
    }
  }
}
```

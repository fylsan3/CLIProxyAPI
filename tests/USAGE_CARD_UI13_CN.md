# 刷新用量与额度卡片调整

2026-11-25。界面版本 accounts-ui13；Go 执行器、账号容器与凭据不变。

- 更新账号资料更名为刷新用量，紧接重启容器按钮。
- 点击先确认；默认焦点为取消。提示：频繁刷新会增加上游查询次数，可能触发限流或风控检查。是否确定刷新？这属于谨慎提示，不代表已证明 Anthropic 的具体识别规则或风险概率。
- 用量按 5 小时、7 天上下排列，显示剩余百分比、重置倒计时和观测来源。额度条表示剩余额度：至少 70% 为绿色，30–70% 为警示色，低于 30% 为红色。未知不当作零；到达所报重置时间不自行置满，标为旧观测。
- 保留现有玻璃卡片、详情原位展开和运行状态配色。

## 参考与重置卡核查

参考 fylsan3/new-api 的 feat/subscription-accounts 分支，读取提交 731b08ee34c3415e16ae305f7fa372b08e5901fa。

- 卡片：https://github.com/fylsan3/new-api/blob/731b08ee34c3415e16ae305f7fa372b08e5901fa/web/src/features/subscription-accounts/components/account-card.tsx
- 重置确认：https://github.com/fylsan3/new-api/blob/731b08ee34c3415e16ae305f7fa372b08e5901fa/web/src/features/subscription-accounts/components/reset-confirm-dialog.tsx
- 后端：https://github.com/fylsan3/new-api/blob/731b08ee34c3415e16ae305f7fa372b08e5901fa/service/cpa_subscription_ops.go

该分支已有重置卡次数/到期展示、使用确认及上游调用实现；结果未知时复用请求标识，防止重复消耗。当前容器版尚未接入对应的重置卡读取和使用。所用 CPA 8.1.1 基线的 ResetQuota 仅清除本地配额/冷却调度状态，不消费上游重置卡。NewAPI 的实现借助 CPA 通用 API 请求能力访问上游，不能把它当作 CPA 内置卡片功能。

后续重置卡方案需把查询/使用放在账号容器内、通过绑定代理执行；先明确只读次数/有效期与主动消费的区别，不在这次界面更新中触发任何真实卡片使用。

## 本地验收

虚构界面：按钮顺序、纵向额度、确认弹窗、取消零请求、确认恰好一次请求、浏览器无错误。检查未知/已到期/未来重置时间。没有用生产账号点击刷新，没有向官方模型发测试请求。

继续保留一小时长任务待验收提醒。异机备份恢复不在开发计划内。

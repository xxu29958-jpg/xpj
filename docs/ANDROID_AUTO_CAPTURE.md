# Android 自动捕获预研（Auto Capture Pre-Research）

> 状态：**v0.6 方向，v0.3.1 不实现**。本文只记录可行性边界与红线，供后续
> 评审。任何 v0.3.x 提交都不应该开启 `NotificationListenerService`、
> `AccessibilityService` 或自动确认逻辑。

## 目标

让 Android 端在用户授权后，自动从微信支付 / 支付宝通知中抓取金额、商家、
时间，作为 **pending 草稿** 进入小票夹，由用户在 Pending 列表中手动
确认。

## 选定方案

`NotificationListenerService` （`android.service.notification`）。

理由：

- 不需要 `BIND_ACCESSIBILITY_SERVICE` 这种高危权限，用户可在系统设置里
  随时撤销。
- 可以读取通知文本字段而不必模拟点击 / 朗读屏幕内容。
- 不需要 root，不影响国行机型上架灰度。

## 红线

1. **绝不自动确认**。所有自动捕获结果一律落入 `pending` 状态，必须经过
   用户手动 `confirm`。
2. **绝不静默上传图片**。本方案只解析通知文本，不读取相册、不截屏。
3. **绝不调用 Accessibility API**。如果未来需要自动捕获微信账单详情，
   必须重新评审。
4. 用户必须能从 Settings 一键关闭通知监听，关闭后下次启动不再请求。
5. 所有自动捕获草稿带 `source=auto_notification` 字段，便于审计与回滚。

## 数据流

```
NotificationListenerService.onNotificationPosted
  └─ NotificationParser (regex)
      └─ AutoDraftRepository.upsertPending(ExpenseEntity {
            status = PENDING,
            source = "auto_notification",
            ledgerId = activeLedgerId,
            serverId = null
         })
      └─ WorkManager: SyncWorker (上传待确认草稿到后端)
```

## 后端契约

- 后端不需要新接口；草稿走现有 `/api/expenses/manual` 或新的
  `/api/expenses/draft` 端点（v0.6 时再定）。
- 后端永远不能跳过 `pending` -> `confirmed` 的人工确认步骤。

## 测试占位

- `NotificationParserTest`：覆盖微信支付、微信收款、支付宝、银联通知文本
  的正负样例。
- `AutoDraftIsolationTest`：自动草稿不出现在 confirmed 列表，不影响 stats
  汇总。

## 回滚

- 只需把 `NotificationListenerService` 在 manifest 中禁用并删除监听权限申
  请，已存的 pending 草稿仍可手动处理或删除。

+++
schema_version = 2
id = "0058"
title = "固定支出提醒的 best-effort 投递语义"
summary = "提醒尽量不漏并压低重复，但不宣称准点或 exactly-once"
current_scope = "Android recurring reminder 的 single-flight、publish outcome、completed dedupe 与稳定通知身份"
date = "2026-07-10"
decision_status = "accepted"
implementation_status = "nonconformant"
verification_status = "failed"
decision_type = "client-interaction"
risk_level = "high"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "Android reminder 维护者"
verification_owner = "独立 Android 并发与交互 reviewer"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "amends"
target = "0046"
scope = "同一 reminder key 只提醒一次的绝对表述"
+++
# 0058 固定支出提醒的 best-effort 投递语义

## [ADR-0058-SCOPE] Context, Scope and Non-goals

[[0046]] 选择 WorkManager 和分层 engine 的方向成立，但 `wasSent → notify → markSent` 无法提供 exactly-once：periodic/one-time 可并发，通知成功后崩溃会重放，先 mark 又会永久漏发。提醒只是本地展示副作用，不是账本事实。

## [ADR-0058-ASSUMPTIONS] Assumptions and Applicability

- 当前提醒在单 Android 进程、单设备本地存储中运行。
- OS 调度、权限和通知服务都可能延迟、拒绝或在调用后中断。
- 多设备各自提醒一次属于预期；服务端不保存 sent 状态。

## [ADR-0058-DRIVERS] Decision Drivers

- 漏掉到期提醒比极少重复更糟，但重复必须主动压低。
- 提醒失败不能写服务端事实、自动建账或阻断手工记账。
- UI/通知状态必须反映真实 publish outcome，不能把早退称为 SENT。

## [ADR-0058-ALTERNATIVES] Alternatives

- **A. 继续承诺 exactly-once**：无法证明，拒绝。
- **B. dispatch 前永久 mark**：崩溃会静默漏提醒，拒绝。
- **C. 成功 publish 后 mark，并用 single-flight/稳定 identity 抑制重复**：选定。
- **D. 把 sent 状态搬到服务端**：当前无多设备协调消费者，拒绝提前扩边界。

## [ADR-0058-DECISION] Decision

### [ADR-0058-C01] publish outcome 决定是否完成去重

dispatcher 必须返回显式 `sent | skipped | failed`。只有最后权限/设置 gate 通过、实际调用 `NotificationManager.notify` 且未抛错才是 `sent`，随后才能持久化 completed key；权限关闭、设置关闭、无效输入、早退或异常均不得 mark。

### [ADR-0058-C02] 所有入口共享 single-flight 与稳定通知身份

periodic 和 one-time 都进入同一 engine single-flight，同进程同一时刻只扫描一轮。通知 `(tag,id)` 从完整 reminder key 稳定派生；commit 后未 mark 的重试更新同一通知槽，并启用 only-alert-once 等价行为。该协议允许极端 crash-window 重放，不允许生成第二个通知身份。

### [ADR-0058-C03] 提醒与账本故障域隔离

Store 只保存本地 completed key；提醒失败、权限缺失或 WorkManager 重试不得创建、确认或修改 Expense/Rule，也不得让后台异常阻断手工账务路径。

## [ADR-0058-CONSEQUENCES] Consequences

- Good：承诺与 Android 调度/通知真实能力一致，常见并发重复被抑制。
- Costs：需要 Mutex/single-flight、显式 outcome、稳定 tag/id 和 TOCTOU 测试。
- Limits：`notify` 成功后进程立即崩溃仍可能重放；risk owner 接受该低影响残余风险。

## [ADR-0058-REVERSIBILITY] Reversibility, Replacement and Retirement

可迁移到服务端多设备协调，但必须新 ADR 定义隐私、identity 和同步；在此之前不得把本地 Store 包装成 exactly-once。

## [ADR-0058-EVIDENCE] Verification and Evidence

- 并发启动 periodic/one-time，同 key 的 dispatcher 调用最多一次。
- 在外层检查后撤销权限，结果必须 skipped/failed 且 Store 不写；mutation 将早退改成 sent 时测试必须失败。
- dispatch 后未 mark 的重试使用相同 tag/id 和 only-alert-once，不创建第二槽位。
- 当前代码没有完整 single-flight，notifier 早退仍可能上报 SENT，因此状态保持 `nonconformant/failed`。

## [ADR-0058-REFERENCES] References

- [[0046]]：WorkManager 作为天级检测器及 active-ledger policy。
- [Android WorkManager](https://developer.android.com/reference/androidx/work/WorkManager)
- [Android NotificationManager](https://developer.android.com/reference/android/app/NotificationManager)

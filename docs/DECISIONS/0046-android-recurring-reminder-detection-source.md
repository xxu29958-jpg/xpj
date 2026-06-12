# 0046 Android 固定支出提醒检测源

* Status: accepted
* Date: 2026-06-12
* Decision makers: 项目维护者
* 适用快照: `feat/notif-loop-pr2` / `29385ab1`
* 对照基线: `main` / `64dbbb33`
* 质量参照: [[0042]] `offline-availability-and-request-idempotency`
* 相关规则 / ADR: `ENGINEERING_RULES.md` §0 / §1 / §7 / §13 / §14，[[0016]], [[0017]], [[0030]], [[0036]], [[0038]], [[0042]]

> 编号注:维护者初稿标 0045;0045 已被 `csrf-signing-key` 占用,落盘时按序改为 0046,内容未动。

## 说明

本 ADR 决定**固定支出 recurring reminder 的检测源**。

它不是一份"可以用 WorkManager 吗"的随手说明，而是一份边界契约：本次只闭合"已有 recurring 数据 + 已有 Android 通知出口，但没有 detection source / sent-key dedupe source"的结构缺口。

承重事实已按当前包回代码 / 文档核实：

* 后端已有 `recurring_items`，并有 `next_expected_date`、`status`、`frequency`、`last_seen_at` 等字段。
* Android 已有 `RecurringItem`、`RecurringRepository`、DTO、ViewModel 和 UI。
* Android 设置已有 `NotificationPreferences.recurringReminders` / `notify_recurring`。
* `TicketboxNotifier` 已有 `ticketbox.recurring` channel、`recurringNotificationContentSpec(merchant)` 和 `onRecurringDue(merchant, dedupeTag)`。
* 当前没有 `RecurringReminderWorker`、没有 recurring reminder scheduler、没有 sent-key store。
* 现有 WorkManager 只服务 outbox drain，不负责 recurring due scan。
* API 文档已写明固定支出不会自动入账，也不会自动创建 pending。

本 ADR **不**解决 `next_expected_date` 自动推进问题。真实 confirmed 账单命中固定支出后如何推进 `last_seen_at / next_expected_date`，必须另开 PR / ADR。

## Context and Problem Statement

固定支出功能已经有正式数据模型和 API。后端 `recurring_items` 存储 `merchant_key`、`merchant_name`、`frequency`、`status`、`last_seen_at`、`next_expected_date`、`baseline_amount_cents`、`last_amount_cents`、`row_version` 等字段；Android 已有 `RecurringItem`、DTO、Repository、ViewModel 和 UI，可以展示正式固定支出、下次日期、暂停 / 归档状态和异常金额提示。

通知侧也已有半闭环。Android `NotificationPreferences` 已有 `recurringReminders` 开关；设置页已经展示"固定支出提醒"；`TicketboxNotifier` 已有 recurring channel、文案、content spec 和 `onRecurringDue(merchant, dedupeTag)` 出口。

当前缺口不是"有没有固定支出数据"，也不是"有没有通知文案"，而是：

**没有一个可靠的检测源周期性检查 active recurring item 是否将到期 / 已逾期，并在本地去重后触发通知。**

电脑后端不能直接把通知塞进 Android 系统通知栏。手机系统通知必须由手机 App 自己发，或者由 FCM / 厂商推送唤醒 App 后再发。当前项目是自托管 / 家庭账本 / sideload Android 形态，没有 FCM / 厂商推送基建，也不应为了固定支出提醒引入这套外部推送平台。

现有 Android WorkManager 只用于 outbox drain。Notification Listener Service 只在捕获支付通知时逐条触发。二者都不是 recurring due scan。

因此问题是：**在当前工程边界下，固定支出提醒的第一检测源应该是什么：Android WorkManager 周期 worker、前台同步钩子，还是服务端推送？**

## Decision Drivers

* `recurringReminders` 作为"固定支出提醒"开关，产品语义上应允许用户不打开 App 时也有机会收到提醒。只在用户打开 App 后提醒，会让这个开关变成弱提醒。
* 当前项目是自托管 / 家庭账本 / sideload Android，不是 SaaS 推送平台。应避免为了一个天级提醒功能引入 FCM / 厂商推送、device token 表、证书和失败重试基建。
* `ENGINEERING_RULES.md` §13 禁止的是 Celery / RQ / workflow engine 这类 backend / 平台级后台任务框架。需要明确 Android 单个 WorkManager worker 是否落入该禁项。
* 提醒必须是只读建议，不得自动生成 pending，不得自动确认账单，不得推进 `next_expected_date`，不得修改 recurring item 状态。
* 提醒策略必须消费 `nextExpectedDate`，不应硬编码当前后端 `frequency` 只有 `monthly`。
* 同一 `ledgerId:itemPublicId:expectedDate:kind` 必须只提醒一次。通知栏覆盖不是可靠去重。
* WorkManager 只能是 scheduler，不得承载 due / overdue policy。业务判断必须拆成纯 Kotlin 可测逻辑。
* `TicketboxNotifier` 只能是 dispatcher，不得拉 API、不得判断 due、不得维护 sent-key。
* 未来前台同步钩子、push-triggered flow、多频率 recurring、snooze / mute、金额异常提醒，都不应要求推翻本次实现。
* 失败降级必须安全：未登录、无 active ledger、网络失败、API 失败、通知权限关闭时，不写任何业务状态，不制造假"已提醒"。

## Considered Options

### A. Android WorkManager periodic worker

手机端注册一个 unique periodic work。Worker 被系统唤醒后读取当前 active ledger 的 active recurring items，根据本地 `today` 和后端返回的 `nextExpectedDate` 判断 due soon / overdue，通过本地 sent-key 去重后调用现有通知出口。

流程：

```
WorkManager periodic work
  -> RecurringReminderWorker
  -> RecurringReminderEngine
  -> RecurringRepository.items(status="active", includeArchived=false)
  -> RecurringReminderPolicy.evaluate(today, item)
  -> RecurringReminderStore.wasSent(key)
  -> TicketboxNotifier / RecurringReminderDispatcher
  -> RecurringReminderStore.markSent(key)
```

优点：

* App 不打开时也有机会提醒，符合"固定支出提醒"的产品承诺。
* 不需要 FCM / 厂商推送。
* 不新增 backend scheduler、Celery、RQ、broker 或 workflow engine。
* WorkManager 依赖和 outbox 调度模式已经存在，新增的是一个更窄的 Android client worker，而不是新的后端平台。
* 如果业务逻辑拆到 `RecurringReminderEngine`，未来前台同步钩子或 push-triggered source 可以复用同一套 policy / store / dispatcher。

缺点：

* Android 后台调度不是准点闹钟，系统可能延迟执行。
* 手机必须能访问后端；电脑后端离线、手机无网络或 token 失效时不会提醒。
* 需要新增本地 sent-key 存储与测试。
* 如果把业务判断写进 Worker，会违反分层并堵死未来扩展。

**结论：选择 A，但只把 WorkManager 当第一 scheduler，不把它变成业务边界。**

### B. Foreground sync hook

App 打开、进入统计页、刷新 recurring 列表或刷新月度统计时，顺手调用 reminder engine 检查 due soon / overdue。

优点：改动最小；零新后台执行面；规则风险最低；如果先抽 `RecurringReminderEngine`，未来仍可加 WorkManager。

缺点：App 不打开就不会提醒；对房租、会员订阅、保险等固定支出来说，"打开账本后才提醒"不是完整提醒能力；如果直接写在 ViewModel / Screen，未来加后台提醒时还要把逻辑从 UI 层抠出来。

**结论：不作为第一检测源。** B 可以作为后续"加速触发入口"，但不能替代后台检测源。若维护者明确裁定"固定支出提醒只承诺 App 内提醒"，B 才是更小的第一版；当前产品语义不按这个弱承诺解释。

### C. Server push

电脑后端周期扫描 recurring items，通过 FCM / 厂商推送把消息发到手机，再由手机展示通知。

优点：服务端可以统一掌握 due / overdue 计算；理论上可支持多设备一致提醒状态。

缺点：当前项目没有 device token 表、push provider、证书、失败重试、厂商通道、token 失效处理；会扩大隐私和出站边界（真实商户名 / 固定支出信息可能进入第三方推送链路）；会把自托管 / sideload / 家庭账本项目推向 SaaS 推送平台形态，收益与成本不匹配；仍需要手机端接收后本地发通知，不能绕过 Android 通知权限。

**结论：当前不选。** 未来如果做 C，应新增 `PushRecurringReminderSource` 或 push-triggered scheduler，并复用同一个 local policy / dedupe / dispatcher，不应推翻本 ADR。

### D. Maintain status quo

保留设置开关、channel、文案和 notifier 出口，但不接检测源。

优点：零新增执行面；零调度风险。

缺点：设置开关会变成"看起来有提醒，实际没有检测源"的半闭环；通知出口长期悬空，用户无法验证功能。

**结论：不选。** 这会保留当前结构缺口。

## Decision Outcome

**Chosen: A. Android WorkManager periodic worker as the first recurring reminder scheduler.**

本 ADR 决定新增 Android 端固定支出提醒检测源，但把检测源拆成四层稳定契约：

```
Scheduler  = 什么时候唤醒
Source     = 从哪里读 recurring candidates
Policy     = 哪些 item 应提醒
Store      = 哪些提醒已经发过
Dispatcher = 如何把提醒交给 Android 通知出口
```

WorkManager 只实现 Scheduler。核心业务闭环由 `RecurringReminderEngine` 编排：

```
RecurringReminderEngine.checkAndNotify()
  -> source.activeItems()
  -> policy.evaluate(today, item)
  -> store.wasSent(decision.key)
  -> dispatcher.dispatch(decision)
  -> store.markSent(decision.key) only if dispatch == SENT
```

### Rule interpretation

Android 单个 WorkManager periodic worker 是移动端平台调度能力，不是 `ENGINEERING_RULES.md` §13 所禁的 backend 后台任务框架。

本 ADR 不引入：Celery、RQ、Redis / broker、backend workflow engine、backend recurring scheduler、FCM / 厂商推送 provider、device token 表、推送证书、新公网 API、AI / OCR / LLM provider 出站。

因此它不构成 §13 "后台任务框架：不做 -> 做"的 MAJOR 反转。**版本裁量：功能增强，建议 MINOR；不是 MAJOR。**

如果维护者未来把"任何新增周期 worker"都解释为 §13 禁项，则应重新裁定为 ADR + MAJOR，或者先走 B foreground sync hook。但本 ADR 的建议是不这样解释：§13 的风险对象是 backend / 平台级任务框架扩张，不是已有 Android client 平台能力下的单个窄 worker。

### Product interpretation

`recurringReminders` 的合理用户预期是：固定支出快到了或已经过期，即使我没打开 App，手机也有机会提醒我。B 无法满足这个预期，C 当前过重，A 是当前边界内最小的完整闭环。

## Boundary Contracts

### Contract 1: Scheduler is not policy

WorkManager 只负责周期唤醒。`RecurringReminderWorker` 不得散写 due soon / overdue 规则，不得拼 sent-key，不得直接判断 frequency，不得直接维护"已提醒"状态。

Worker 只能：

1. 从 `TicketboxApplication.container` 或等价 DI 入口取得 `RecurringReminderEngine`。
2. 调用 `engine.checkAndNotify()`。
3. 把 engine outcome 映射成 WorkManager `Result.success()` 或 `Result.retry()`。

业务判断必须在纯 Kotlin 可测层完成。

### Contract 2: Engine owns orchestration, not business truth

`RecurringReminderEngine` 负责串联 source / policy / store / dispatcher，但它不拥有 due 规则本身。

Engine 可以决定执行顺序：读取设置 / session / active ledger 前置条件 → 从 source 拉 active recurring items → 对每个 item 调 policy → 查 store 是否已提醒 → 调 dispatcher → 成功发出后 mark sent。

Engine 不得：改写服务端 recurring item、创建 pending、确认 expense、把 frequency 转换成下一次日期、在失败时写业务补偿状态。

### Contract 3: Policy consumes `nextExpectedDate`, not `frequency`

`RecurringReminderPolicy` 只消费：

* `today: LocalDate`，由可注入 clock / date provider 提供。
* `item.status`。
* `item.nextExpectedDate`。
* `item.publicId` / `item.ledgerId` / `item.merchant`，用于生成 decision 和通知上下文。

当前后端 `frequency` 只有 `monthly`，但提醒层不得写死 monthly。

MVP policy：

```
if status != active -> NONE
if nextExpectedDate == null -> NONE
if nextExpectedDate < today -> OVERDUE
after that, if today <= nextExpectedDate <= today + 7 days -> DUE_SOON
else -> NONE
```

`OVERDUE` 优先于 `DUE_SOON`。`DUE_SOON` 和 `OVERDUE` 是不同 `ReminderKind`。同一 expected date 允许到期前提醒一次、逾期后再提醒一次。

### Contract 4: Source is read-only

当前 source 只通过 Android `RecurringRepository.items(status="active", includeArchived=false)` 读取后端 API。

禁止：自动创建 pending、自动确认账单、自动推进 `next_expected_date`、自动修改 recurring item 状态、自动 pause / archive recurring item、写入任何服务端"已提醒"状态。

`next_expected_date` 的自动推进是另一项准确性问题，必须单独 PR / ADR。它不能混进本 ADR。

### Contract 5: Dedup is explicit

同一提醒的 sent-key 格式为：

```
v1:{ledgerId}:{itemPublicId}:{expectedDate}:{kind}
```

其中：`ledgerId` 防止多账本串台；`itemPublicId` 锁定固定支出项；`expectedDate` 允许下一周期重新提醒；`kind` 区分 `DUE_SOON` / `OVERDUE` / 未来 `AMOUNT_ANOMALY`。

`NotificationManager.notify(tag, id)` 的 tag 可以复用 sent-key，但它只能控制通知栏覆盖，不能替代 sent-key。原因：通知栏覆盖不能阻止下一次 Worker 再次发同一提醒。

`RecurringReminderStore` MVP 可以用 SharedPreferences；如果后续增加 snooze / mute / history，再升 Room 表。

Store 至少提供：

```
wasSent(key): Boolean
markSent(key)
prune(cutoff) // 可选，但必须有测试或明确 defer
```

Key retention 不是业务正确性底座；key 丢失最多导致重复提醒，不会写错账本。MVP 可选择长保留或只清理 180 / 365 天以前的 key，但不得在同一 expected date 仍可能被检查时频繁清掉。

### Contract 6: Mark sent only after actual dispatch

Engine 只能在通知确实被 dispatcher 接受后 `markSent(key)`。

当前 `TicketboxNotifier.onRecurringDue(...)` 返回 `Unit`，这不足以支撑"通知权限关闭不 mark sent"的测试。实现本 ADR 时必须满足下面任一形态：

1. 将 `onRecurringDue(...)` 改为返回 `Boolean` 或 `NotificationDispatchResult`。
2. 新增 `RecurringReminderDispatcher` wrapper，由 wrapper 检查开关 / 权限并返回 dispatch outcome。

建议 outcome：

```
SENT
SKIPPED_DISABLED
SKIPPED_PERMISSION_DENIED
SKIPPED_INVALID_INPUT
```

只有 `SENT` 可以触发 `markSent(key)`。

### Contract 7: Notifier remains a dispatcher

`TicketboxNotifier` 不得拉 API，不得读取 recurring 列表，不得判断 due soon / overdue，不得维护 sent-key。

它只负责：读取 `recurringReminders` 开关、检查系统通知权限、创建 / 复用 notification channel、构造 private notification 和脱敏 public version、发系统通知、返回是否实际发出。

MVP 可以让 `DUE_SOON` / `OVERDUE` 共用现有 `recurringNotificationContentSpec(merchant)`；kind 先用于 dedupe。未来要区分"即将到期 / 已逾期"文案，应改 dispatcher / content spec，但不改变 source / policy / store 契约。

### Contract 8: Failure and retry semantics stay bounded

Engine / Worker 失败行为：

* 未登录、server URL 为空、无 active ledger：safe success，不发通知，不 mark sent。
* `recurringReminders=false`：safe success，不发通知，不 mark sent。
* 系统通知权限关闭：safe success，不发通知，不 mark sent。
* active items 为空：success。
* API 401 / 403：safe success 或 session 失效路径处理，不 mark sent，不无限 retry。
* 网络 IO / timeout / 502 / 503 / 504 等瞬时失败：可返回 transient failure，由 Worker 映射成 `Result.retry()`。
* 单条 item 日期解析失败：跳过该 item，轻量日志，不让整个 worker 失败。

任何失败都不得写服务端业务状态。日志不得包含 token、header、完整商户明细、账单明细或通知原文。必要日志只写 outcome / count / error class。

### Contract 9: Cadence is day-level, not outbox-level

固定支出提醒是日期窗口，不是 outbox drain。不得因为 outbox drain 使用 15 分钟 heartbeat，就把 recurring reminder 也默认设为 15 分钟。

MVP cadence 建议：

```
DUE_SOON_WINDOW_DAYS = 7
REPEAT_INTERVAL_HOURS = 24
OPTIONAL_FLEX_INTERVAL_HOURS = 6
```

WorkManager 的 15 分钟只是系统 floor，不是本功能的合理默认。固定支出提醒只承诺"有机会提醒"，不承诺准点。

当用户打开 App、开启 `recurringReminders` 或刷新 recurring 列表时，可以额外 enqueue one-time check 作为加速触发，但不改变 periodic scheduler 的低压默认。

### Contract 10: Privacy and side effects stay bounded

本 ADR 不引入 AI / OCR / LLM provider 出站；不上传图片、通知原文、账单明细、商户明细给第三方；不新增推送 provider，不新增 device token，不新增公网 API。

系统通知 private 版可以显示固定支出名 / 商户名；public lock-screen 版必须继续使用脱敏摘要。

### Contract 11: Active ledger only

MVP 只扫描当前 Android 绑定 session 的 active ledger。不做 owner-console 式"扫描所有账本"。跨账本提醒、多成员多设备一致提醒、服务端已提醒状态，均是未来新决策。

### Contract 12: Extensibility is interface stability, not premature push

扩展性不等于现在直接上服务端推送。本 ADR 的扩展性是：

```
Scheduler 可换
Source 可换
Policy 稳定
Store 可升级
Dispatcher 稳定
```

未来入口：

```
Foreground sync hook   -> RecurringReminderEngine
Push-triggered source  -> RecurringReminderEngine
Local cache source     -> RecurringReminderEngine
```

不能让 WorkManager 成为唯一业务入口，也不能让 ViewModel / Screen 各自散写 due 判断。

## Implementation Shape

建议新增 Android 组件：

```
com.ticketbox.notification.recurring.RecurringReminderKind
com.ticketbox.notification.recurring.RecurringReminderDecision
com.ticketbox.notification.recurring.RecurringReminderPolicy
com.ticketbox.notification.recurring.RecurringReminderSource
com.ticketbox.notification.recurring.RepositoryRecurringReminderSource
com.ticketbox.notification.recurring.RecurringReminderStore
com.ticketbox.notification.recurring.SharedPrefsRecurringReminderStore
com.ticketbox.notification.recurring.RecurringReminderDispatcher
com.ticketbox.notification.recurring.NotifierRecurringReminderDispatcher
com.ticketbox.notification.recurring.RecurringReminderEngine
com.ticketbox.notification.recurring.RecurringReminderScheduler
com.ticketbox.notification.recurring.WorkManagerRecurringReminderScheduler
com.ticketbox.notification.recurring.RecurringReminderWorker
```

最小调用关系：

```
TicketboxApplication.onCreate
  -> container.recurringReminderScheduler.ensurePeriodic(context)

RecurringReminderWorker.doWork
  -> container.recurringReminderEngine.checkAndNotify()
```

WorkManager contract：

* 使用 unique periodic work，例如 `ticketbox.recurring.reminders.periodic`。
* 使用 tag，例如 `ticketbox.recurring.reminders`。
* 加 `NetworkType.CONNECTED` 约束。
* 默认 repeat interval 为 24h；不使用 outbox 的 15min heartbeat。
* `ensurePeriodic()` 必须幂等；App 冷启动可重复调用。
* 可在设置开关打开时 enqueue one-time check，但 one-time 也必须走同一个 engine。
* 不引入 AlarmManager 精确闹钟、foreground service、boot receiver 或自定义常驻进程。

Source contract：

```kotlin
interface RecurringReminderSource {
    suspend fun activeItems(): Result<List<RecurringItem>>
}
```

Policy contract：

```kotlin
enum class RecurringReminderKind { DUE_SOON, OVERDUE }

data class RecurringReminderDecision(
    val key: String,
    val kind: RecurringReminderKind,
    val ledgerId: String,
    val itemPublicId: String,
    val merchant: String,
    val expectedDate: LocalDate,
)
```

Dispatcher contract：

```kotlin
enum class RecurringReminderDispatchOutcome {
    SENT, SKIPPED_DISABLED, SKIPPED_PERMISSION_DENIED, SKIPPED_INVALID_INPUT,
}
```

Engine outcome：

```kotlin
sealed interface RecurringReminderRunOutcome {
    data class Success(
        val scanned: Int, val due: Int, val sent: Int,
        val skippedAlreadySent: Int, val skippedDispatch: Int,
    ) : RecurringReminderRunOutcome

    data class TransientFailure(val reason: String) : RecurringReminderRunOutcome
}
```

这些类型名可在实现时微调，但职责边界不得改变。

## Consequences

Good:

* 固定支出提醒从"设置开关 + 通知出口"闭合为真实可触达能力。
* 不依赖 FCM / 厂商推送，保留自托管 / sideload 边界。
* 不新增 backend 后台任务框架。
* due / overdue 规则成为纯函数，可直接 JVM 单测。
* WorkManager、foreground hook、未来 push-triggered flow 都能复用同一个 engine。
* `nextExpectedDate` 成为提醒层唯一日期契约，未来多频率 recurring 不要求重写 Android 提醒逻辑。
* 本地 sent-key 把"通知栏覆盖"和"跨 worker run 去重"分开，边界清楚。

Bad / Costs:

* Android 后台调度不精确，不能承诺固定几点提醒。
* 手机和后端必须都可达；电脑后端离线时不会提醒。
* 需要新增本地 store、scheduler、worker 和一组测试。
* `TicketboxNotifier.onRecurringDue` 当前返回 `Unit`，需要返回 dispatch outcome 或通过 wrapper 弥补。
* 本地 sent-key 是单设备状态；多设备各自可能提醒一次。
* 如果 `next_expected_date` 不自动推进，提醒只能围绕旧 expected date 发一次 due-soon / overdue；长期准确性不足。

Reversibility:

* 可取消 unique periodic work。
* 可保留 `RecurringReminderEngine`、policy、store 和 notifier 出口，供 foreground hook 使用。
* 回退不需要服务端迁移，因为本 ADR 不写服务端业务状态。
* 回退后损失后台提醒能力，但不会破坏账本数据。

## Confirmation

必须补以下测试或等价验证。没有这些测试，不视为本 ADR 落地完成。

**Policy tests**（`RecurringReminderPolicyTest`）：`active + today <= nextExpectedDate <= today+7` -> `DUE_SOON`；`active + nextExpectedDate < today` -> `OVERDUE`；`paused` / `archived` / unknown status -> `NONE`；`nextExpectedDate == null` -> `NONE`；blank / unparsable `nextExpectedDate` -> `NONE` 或 item-level skip；future outside window -> `NONE`；policy 不读取、不分支 `frequency == monthly`；`OVERDUE` 优先于 `DUE_SOON`；`ledgerId:itemPublicId:expectedDate:kind` key 稳定生成。

**Store tests**（`RecurringReminderStoreTest`）：同一 key 只提醒一次；不同 `ledgerId` / `itemPublicId` 不串台；不同 `expectedDate` 可再次提醒；`DUE_SOON` 和 `OVERDUE` 是不同 key；prune 策略若实现，必须证明不会清掉刚写入 key。

**Dispatcher / notifier tests**：`recurringReminders=false` -> `SKIPPED_DISABLED` 不发通知；系统通知权限关闭 -> `SKIPPED_PERMISSION_DENIED` 不发通知；merchant blank -> fallback 或 `SKIPPED_INVALID_INPUT`，行为明确；成功 recurring dispatch 使用 `ticketbox.recurring` channel；public version 使用固定支出脱敏摘要；已有 `TicketboxNotifierContentSpecTest` 继续钉住 recurring content spec。

**Engine tests**（`RecurringReminderEngineTest`）：preference off -> 不拉 source 或拉后不发，且不 mark sent（行为固定）；未登录 / 无 active ledger -> safe success 不 mark sent；source API failure -> transient failure 不 mark sent；policy NONE -> 不查 / 不写 sent key；store already sent -> 不 dispatch；dispatch skipped -> 不 mark sent；dispatch SENT -> mark sent；多 item 独立处理，单条 bad date 不影响其他 item；due soon 与 overdue kind 分别去重。

**Worker tests**（`RecurringReminderWorkerTest`）：Worker 调用 engine 而非直接调用 repository / policy / notifier；`Success` -> `Result.success()`；`TransientFailure` -> `Result.retry()`；container 未 ready 的防御路径明确（retry 或 safe success，必须有测试）；不把单条 skipped notification 映射成 WorkManager failure。

**Scheduler tests**（`RecurringReminderSchedulerTest`）：unique periodic work name；`NetworkType.CONNECTED`；`ensurePeriodic()` 幂等；cadence 使用本 ADR 常量不继承 outbox 15min；one-time trigger 如实现，必须 unique work + KEEP / UPDATE 语义明确。

**Contract / regression**：`RecurringDtoContractTest` 钉住 `next_expected_date`、`status`、`ledger_id`、`public_id`；`TicketboxNotifierContentSpecTest` 钉住 recurring channel / title / body / public summary / action；设置页测试：`recurringReminders` 开关状态与通知权限状态展示不倒退。

**Review checklist**：Worker 内没有 due soon / overdue 细节；Notifier 内没有 API 拉取；Repository / Source 没有写接口调用；没有新增 FCM / push provider / device token；没有新增 backend scheduler；没有创建 pending / confirm expense / 推进 `next_expected_date`；没有 15min recurring heartbeat；日志不含 token / header / 商户明细 / 通知原文。

## Rollout Slices

* **Slice 0: ADR only** — 接受本 ADR。不在 ADR 同 PR 偷塞 worker。
* **Slice 1: Notifier dispatch outcome** — 补 `onRecurringDue` 返回结果或新增 `NotifierRecurringReminderDispatcher` wrapper；让"权限关闭 / 开关关闭不 mark sent"可测试。
* **Slice 2: Pure policy + sent-key** — `RecurringReminderKind` / `RecurringReminderDecision` / `RecurringReminderPolicy` / sent-key builder + 纯 JVM policy tests。不接 WorkManager。
* **Slice 3: Store** — `RecurringReminderStore` / `SharedPrefsRecurringReminderStore` + store tests。
* **Slice 4: Engine + source adapter** — `RecurringReminderSource` / `RepositoryRecurringReminderSource` / `RecurringReminderEngine`；engine tests 全部用 fake source / fake store / fake dispatcher。这片证明业务契约，不引入 Android scheduler 噪音。
* **Slice 5: WorkManager scheduler / worker** — `RecurringReminderWorker` / `RecurringReminderScheduler` / `WorkManagerRecurringReminderScheduler`；`AppContainer` 组装；`TicketboxApplication.onCreate` 调 `ensurePeriodic()`；worker / scheduler tests。
* **Slice 6: Optional foreground hook** — recurring list refresh 或 stats refresh 后调用同一个 engine；加速触发不是替代 A；禁止把 due 判断写进 ViewModel / Screen。
* **Slice 7: Accuracy follow-up（另开 PR / ADR）** — confirmed expense 命中 active recurring item 后安全推进 `last_seen_at` / `next_expected_date`。不是 reminder worker 的职责。
* **Slice 8: UX follow-up（另开 PR）** — 通知点击目标页、snooze、mute、per-item toggle、overdue 专属文案、amount anomaly reminder。

## Non-goals

本 ADR 不做：自动生成 pending expense；自动确认 expense；自动匹配真实账单和 recurring item；自动推进 `next_expected_date`；服务端 recurring scan；FCM / 厂商推送；device token 表；push provider；Celery / RQ / broker / workflow engine；exact alarm；foreground service；boot receiver；常驻进程；跨账本扫描；多设备"已提醒"一致状态；AI / OCR / LLM provider 调用；对外暴露新公网 API。

## Open Risks

1. **`next_expected_date` 自动推进仍缺。** 这是最大产品债。没有它，提醒只能围绕旧 expected date 发 due-soon / overdue；下一周期准确性不足。
2. **Android 后台调度是 best-effort。** WorkManager 可能因电池、待机桶、OEM 策略、force-stop 延迟。此功能承诺"有机会提醒"，不承诺准点。
3. **本地去重是单设备。** 多台 Android 设备可能各提醒一次。跨设备去重需要服务端状态，是新决策。
4. **MVP 只扫 active ledger。** 多账本用户不会收到非当前 active ledger 的后台提醒。
5. **Notifier outcome seam 必须补。** 保持 `onRecurringDue(): Unit` 会让 sent-key 写入时机不可验证。
6. **Cadence 需要产品校准。** 本 ADR 建议 24h 起步。若用户反馈太慢，可调 12h 或增加 foreground one-time trigger；不应直接降到 15min。
7. **权限关闭后的体验要清楚。** 设置页已经处理通知权限状态，但 reminder engine 也必须 fail closed。

## More Information

* [[0042]] 是本 ADR 的质量标尺：具体结构缺口、根因拆解、拒绝方案、边界契约、代价、Confirmation 和 rollout slices。
* [[0030]] 表明项目偏好窄边界、单机 / 平台原生能力，不为小任务引入 broker / worker framework。
* [[0036]] 表明 recurring / fixed expense 真实商户信息属于隐私敏感信息，不能为了提醒功能进入外部 provider / push 链路。
* 适用快照 `feat/notif-loop-pr2 / 29385ab1`（PR #66）已有 recurring notification outlet，缺的是 detection source。

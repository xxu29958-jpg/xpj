package com.ticketbox.notification.recurring

/**
 * ADR-0046 Slice 1：一次提醒投递的结果。**只有 [SENT] 允许调用 store.markSent(key)**
 * （Contract 6：通知确实被接受后才记「已提醒」，否则权限/开关关闭会写出假「已提醒」）。
 *
 * - [SENT]：系统通知确实发出。
 * - [SKIPPED_DISABLED]：固定支出提醒开关关闭。
 * - [SKIPPED_PERMISSION_DENIED]：系统通知权限关闭 / 未授予。
 * - [SKIPPED_INVALID_INPUT]：输入不可用（如 ledgerId / itemPublicId 为空）。商家为空走 fallback 文案
 *   不算 invalid（与草稿通知一致），故本值由 dispatcher 对结构性空值兜底，不由 notifier 产出。
 */
enum class RecurringReminderDispatchOutcome {
    SENT,
    SKIPPED_DISABLED,
    SKIPPED_PERMISSION_DENIED,
    SKIPPED_INVALID_INPUT,
}

/**
 * ADR-0046 四层契约的 Dispatcher：把一条 [RecurringReminderDecision] 交给 Android 通知出口，
 * 返回 [RecurringReminderDispatchOutcome]。这是 [RecurringReminderEngine] 的接缝——
 * engine 依赖本接口而非具体 [TicketboxNotifier][com.ticketbox.notification.TicketboxNotifier]，故 EngineTest 可用 fake dispatcher 钉
 * 「SENT 才 markSent」「skipped 不 markSent」（Contract 6/7）。
 *
 * 实现不得：拉 API、读 recurring 列表、判断 due/overdue、维护 sent-key（那是 source/policy/store 的事）。
 */
fun interface RecurringReminderDispatcher {
    fun dispatch(decision: RecurringReminderDecision, binding: com.ticketbox.data.repository.LogicalSessionBinding): RecurringReminderDispatchOutcome
}

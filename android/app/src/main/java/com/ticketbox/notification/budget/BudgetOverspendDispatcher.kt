package com.ticketbox.notification.budget


/**
 * 一次预算超支提醒投递的结果。**只有 [SENT] 允许调用 store.markSent(key)**（镜像 recurring 的
 * Contract 6：通知确实被接受后才记「已提醒」，否则权限/开关关闭会写出假「已提醒」、
 * 用户打开开关后整月再也收不到）。
 *
 * - [SENT]：系统通知确实发出。
 * - [SKIPPED_DISABLED]：「预算超支提醒」开关关闭。
 * - [SKIPPED_PERMISSION_DENIED]：系统通知权限关闭 / 未授予。
 */
enum class BudgetOverspendDispatchOutcome {
    SENT,
    SKIPPED_DISABLED,
    SKIPPED_PERMISSION_DENIED,
}

/**
 * 把一条 [BudgetOverspendDecision] 交给 Android 通知出口的接缝——[BudgetOverspendChecker]
 * 依赖本接口而非具体 [TicketboxNotifier][com.ticketbox.notification.TicketboxNotifier]，
 * 故 CheckerTest 可用 fake dispatcher 钉「SENT 才 markSent」「skipped 不 markSent」。
 *
 * 实现不得：拉 API、判超支、维护 sent-key（那是 source / policy / store 的事）。
 */
fun interface BudgetOverspendDispatcher {
    fun dispatch(decision: BudgetOverspendDecision, binding: com.ticketbox.data.repository.LogicalSessionBinding): BudgetOverspendDispatchOutcome
}

package com.ticketbox.notification.budget

import com.ticketbox.ui.components.formatAmount

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
    fun dispatch(decision: BudgetOverspendDecision): BudgetOverspendDispatchOutcome
}

/**
 * 生产实现：把超出金额格式化成本位币串（[formatAmount]，不散写 ÷100），委托
 * [TicketboxNotifier.onBudgetOverspent][com.ticketbox.notification.TicketboxNotifier.onBudgetOverspent]。
 *
 * 依赖窄函数接缝 `(overspentAmount, dedupeTag) -> outcome` 而非具体 notifier（镜像
 * [NotifierRecurringReminderDispatcher][com.ticketbox.notification.recurring.NotifierRecurringReminderDispatcher]）：
 * AppContainer 用方法引用 `notifier::onBudgetOverspent` 接线；测试注 lambda 直测
 * 「格式化 + key 透传」而不必构造需要 Context 的 notifier（本模块无 Robolectric）。
 * 开关 / 权限门（→ SENT / SKIPPED_*）是 Android 绑定逻辑，集中在 notifier 一处。
 */
class NotifierBudgetOverspendDispatcher(
    private val onBudgetOverspent: (overspentAmount: String, dedupeTag: String) -> BudgetOverspendDispatchOutcome,
) : BudgetOverspendDispatcher {
    override fun dispatch(decision: BudgetOverspendDecision): BudgetOverspendDispatchOutcome =
        onBudgetOverspent(formatAmount(decision.overspentCents), decision.key)
}

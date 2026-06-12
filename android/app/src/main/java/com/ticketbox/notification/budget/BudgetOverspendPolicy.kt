package com.ticketbox.notification.budget

import com.ticketbox.domain.model.BudgetMonthly

/**
 * 一条预算超支提醒的判定结果（轴 6 主动性 · 预算超支通知）。
 *
 * @property key 本地去重 sent-key（[budgetOverspendSentKey] 构造，月级：同账本同月只提醒一次）。
 * @property ledgerId 判定时的账本。
 * @property month 预算月（来自服务端响应 [BudgetMonthly.month]，`yyyy-MM`）。
 * @property overspentCents 超出金额（本位币分，服务端 `overspent = max(-remaining, 0)` 的镜像值）。
 */
data class BudgetOverspendDecision(
    val key: String,
    val ledgerId: String,
    val month: String,
    val overspentCents: Long,
)

/**
 * 预算超支 sent-key：`v1:budget:{ledgerId}:{month}`。月级粒度是有意的防骚扰取舍——
 * 一个月内「超支 → 调高预算回到线内 → 再超支」不会二次提醒（KDoc 级契约，改粒度先改这里）。
 */
fun budgetOverspendSentKey(ledgerId: String, month: String): String = "v1:budget:$ledgerId:$month"

/**
 * 纯函数判定（零 Android / IO 依赖，单测直测）：这份月度预算是否构成「超支提醒」。
 *
 * - 未配置预算（[BudgetMonthly.configured] = false）→ null：没立预算就没有超支概念。
 * - [BudgetMonthly.overspentAmountCents] <= 0 → null：服务端口径
 *   `overspent = max(available - spent < 0 ? spent - available : 0)`，> 0 即超支。
 *   刻意只读服务端算好的字段、不在客户端重算（excluded / rollover / 汇率折算都在服务端口径里，
 *   本地重算必然分叉）。
 */
fun evaluateBudgetOverspend(ledgerId: String, budget: BudgetMonthly): BudgetOverspendDecision? {
    if (!budget.configured) return null
    if (budget.overspentAmountCents <= 0L) return null
    return BudgetOverspendDecision(
        key = budgetOverspendSentKey(ledgerId, budget.month),
        ledgerId = ledgerId,
        month = budget.month,
        overspentCents = budget.overspentAmountCents,
    )
}

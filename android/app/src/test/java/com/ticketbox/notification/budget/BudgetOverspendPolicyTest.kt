package com.ticketbox.notification.budget

import com.ticketbox.domain.model.BudgetMonthly
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/**
 * [evaluateBudgetOverspend] / [budgetOverspendSentKey] 纯函数判定矩阵（轴 6 预算超支通知）。
 * 口径契约：只读服务端算好的 [BudgetMonthly.overspentAmountCents]，客户端不重算。
 */
class BudgetOverspendPolicyTest {

    @Test
    fun overspentConfiguredBudgetYieldsDecisionWithServerAmount() {
        val decision = evaluateBudgetOverspend("ledger-1", budgetOf(overspentCents = 12_345L))
        assertEquals("v1:budget:ledger-1:2026-06", decision?.key)
        assertEquals("ledger-1", decision?.ledgerId)
        assertEquals("2026-06", decision?.month)
        assertEquals(12_345L, decision?.overspentCents)
    }

    @Test
    fun unconfiguredBudgetYieldsNullEvenIfOverspentFieldIsPositive() {
        // 防御：未配置预算就没有超支概念——即使响应里 overspent 字段异常带值也不提醒。
        assertNull(evaluateBudgetOverspend("ledger-1", budgetOf(configured = false, overspentCents = 500L)))
    }

    @Test
    fun zeroOverspendYieldsNull() {
        assertNull(evaluateBudgetOverspend("ledger-1", budgetOf(overspentCents = 0L)))
    }

    @Test
    fun negativeOverspendYieldsNull() {
        // 服务端口径 overspent = max(-remaining, 0) 不会为负；负值按防御处理不提醒。
        assertNull(evaluateBudgetOverspend("ledger-1", budgetOf(overspentCents = -1L)))
    }

    @Test
    fun sentKeyIsMonthGrainPerLedger() {
        // 月级 sent-key：同账本同月恒等（一月一响的防骚扰粒度），跨账本/跨月互不相同。
        assertEquals(budgetOverspendSentKey("L1", "2026-06"), budgetOverspendSentKey("L1", "2026-06"))
        assertEquals("v1:budget:L1:2026-07", budgetOverspendSentKey("L1", "2026-07"))
        assertEquals("v1:budget:L2:2026-06", budgetOverspendSentKey("L2", "2026-06"))
    }
}

/** 构造仅关心 configured / overspent 维度的月度预算，其余字段填自洽常量。 */
internal fun budgetOf(
    month: String = "2026-06",
    configured: Boolean = true,
    overspentCents: Long = 0L,
): BudgetMonthly = BudgetMonthly(
    ledgerId = "ledger-1",
    month = month,
    configured = configured,
    totalAmountCents = 100_000L,
    rolloverAmountCents = 0L,
    fixedAmountCents = 0L,
    nonMonthlyAmountCents = 0L,
    flexBudgetCents = 100_000L,
    spentAmountCents = 100_000L + overspentCents,
    excludedAmountCents = 0L,
    remainingAmountCents = -overspentCents,
    overspentAmountCents = overspentCents,
    excludedCategories = emptyList(),
    excludedBreakdown = emptyList(),
    categoryBudgets = emptyList(),
    updatedAt = null,
)

package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.BudgetProgress
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/**
 * 轴3 bullet 预算条纯函数:[budgetTickFraction](超支时预算刻度位)与
 * [budgetSpentPercent](真实占比,可 >100;预算不可用退回截断版)。
 */
class StatsMetricGridBulletTest {

    private fun budgetOf(
        budgetCents: Long,
        spentCents: Long,
        overBudget: Boolean = spentCents > budgetCents,
    ) = BudgetProgress(
        month = "2026-06",
        budgetCents = budgetCents,
        spentCents = spentCents,
        remainingCents = budgetCents - spentCents,
        progress = if (budgetCents > 0L) {
            (spentCents.toFloat() / budgetCents.toFloat()).coerceIn(0f, 1f)
        } else {
            0f
        },
        percent = 0,
        overBudget = overBudget,
    )

    @Test
    fun tickIsNullWithinBudgetAndBudgetOverSpentRatioWhenOver() {
        assertNull(budgetTickFraction(budgetOf(budgetCents = 100_000L, spentCents = 60_000L)))
        // 超支 25%:轨道上限=spent=125k,预算刻度在 100k/125k=0.8。
        assertEquals(0.8f, budgetTickFraction(budgetOf(budgetCents = 100_000L, spentCents = 125_000L)))
    }

    @Test
    fun tickGuardsDegenerateInputs() {
        // overBudget 标志在但数据退化(零预算/零支出/未真超):一律 null 走普通条,绝不除零。
        assertNull(budgetTickFraction(budgetOf(budgetCents = 0L, spentCents = 500L, overBudget = true)))
        assertNull(budgetTickFraction(budgetOf(budgetCents = 100L, spentCents = 0L, overBudget = true)))
        assertNull(budgetTickFraction(budgetOf(budgetCents = 100L, spentCents = 100L, overBudget = true)))
    }

    @Test
    fun spentPercentReportsRealRatioBeyondHundred() {
        // 旧行为 progress 截断在 1 → 超支永远显示 100%;bullet 后数字报真实占比。
        assertEquals(125, budgetSpentPercent(budgetOf(budgetCents = 100_000L, spentCents = 125_000L)))
        assertEquals(60, budgetSpentPercent(budgetOf(budgetCents = 100_000L, spentCents = 60_000L)))
        // 预算不可用:退回截断版 progress 百分比,绝不除零。
        assertEquals(0, budgetSpentPercent(budgetOf(budgetCents = 0L, spentCents = 500L)))
    }
}

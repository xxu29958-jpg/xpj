package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull

class BudgetProgressStatusTest {
    @Test
    fun unconfiguredBudgetDoesNotProduceProgress() {
        val budget = budgetMonthly(
            configured = false,
            totalAmountCents = 100_000L,
        )

        assertEquals(BudgetProgressStatus.Unconfigured, budget.toBudgetProgressStatus())
        assertNull(budget.toBudgetProgress())
    }

    @Test
    fun configuredBudgetWithoutPositiveAvailableAmountKeepsConfiguredStatus() {
        val budget = budgetMonthly(
            configured = true,
            totalAmountCents = 0L,
            rolloverAmountCents = 0L,
        )

        assertEquals(BudgetProgressStatus.ConfiguredWithoutProgress, budget.toBudgetProgressStatus())
        assertNull(budget.toBudgetProgress())
    }

    @Test
    fun configuredBudgetWithPositiveAvailableAmountProducesProgress() {
        val budget = budgetMonthly(
            configured = true,
            totalAmountCents = 100_000L,
            spentAmountCents = 25_000L,
        )

        assertEquals(BudgetProgressStatus.Progress, budget.toBudgetProgressStatus())
        assertEquals(25L, assertNotNull(budget.toBudgetProgress()).percent)
        val aggregateBoundary = budgetMonthly(
            configured = true,
            totalAmountCents = 1L,
            spentAmountCents = 9_007_199_254_740_991L,
        )
        assertEquals(900_719_925_474_099_100L, aggregateBoundary.spentPercent)
        assertEquals(aggregateBoundary.spentPercent, assertNotNull(aggregateBoundary.toBudgetProgress()).percent)
    }
}

private fun budgetMonthly(
    configured: Boolean,
    totalAmountCents: Long,
    rolloverAmountCents: Long = 0L,
    spentAmountCents: Long = 10_000L,
): BudgetMonthly = BudgetMonthly(
    ledgerId = "ledger-1",
    month = "2026-07",
    configured = configured,
    totalAmountCents = totalAmountCents,
    rolloverAmountCents = rolloverAmountCents,
    fixedAmountCents = 0L,
    nonMonthlyAmountCents = 0L,
    flexBudgetCents = totalAmountCents + rolloverAmountCents,
    spentAmountCents = spentAmountCents,
    excludedAmountCents = 0L,
    remainingAmountCents = totalAmountCents + rolloverAmountCents - spentAmountCents,
    overspentAmountCents = (spentAmountCents - totalAmountCents - rolloverAmountCents).coerceAtLeast(0L),
    excludedCategories = emptyList(),
    excludedBreakdown = emptyList(),
    categoryBudgets = emptyList(),
    updatedAt = "2026-07-05T00:00:00Z",
    rowVersion = if (configured) 1L else null,
)

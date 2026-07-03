package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.ReportCategoryComparison
import kotlin.test.Test
import kotlin.test.assertEquals

class ReportsCategoryComparisonModeTest {
    @Test
    fun doesNotClaimComparisonWithoutHistoryBaseline() {
        val currentOnly = categoryComparisonChartRows(
            listOf(
                comparisonRow(category = "dining", amountCents = 1_200L, previousAmountCents = 0L),
                ReportCategoryComparison(
                    category = "missing-history-sample",
                    amountCents = 900L,
                    count = 1,
                    previousAmountCents = 8_000L,
                    previousCount = 0,
                    deltaAmountCents = -7_100L,
                    deltaCount = -1,
                    yearOverYearAmountCents = 7_000L,
                    yearOverYearCount = 0,
                    yearOverYearDeltaAmountCents = -6_100L,
                    yearOverYearDeltaCount = -1,
                ),
            ),
        )
        val comparable = categoryComparisonChartRows(
            listOf(comparisonRow(category = "transport", amountCents = 1_200L, previousAmountCents = 800L)),
        )

        assertEquals(CategoryComparisonMode.CurrentOnly, categoryComparisonMode(currentOnly))
        assertEquals(CategoryComparisonMode.Comparison, categoryComparisonMode(comparable))
    }

    private fun comparisonRow(
        category: String,
        amountCents: Long,
        previousAmountCents: Long,
        yearOverYearAmountCents: Long = 0L,
    ) = ReportCategoryComparison(
        category = category,
        amountCents = amountCents,
        count = 1,
        previousAmountCents = previousAmountCents,
        previousCount = if (previousAmountCents > 0L) 1 else 0,
        deltaAmountCents = amountCents - previousAmountCents,
        deltaCount = 0,
        yearOverYearAmountCents = yearOverYearAmountCents,
        yearOverYearCount = if (yearOverYearAmountCents > 0L) 1 else 0,
        yearOverYearDeltaAmountCents = amountCents - yearOverYearAmountCents,
        yearOverYearDeltaCount = 0,
    )
}

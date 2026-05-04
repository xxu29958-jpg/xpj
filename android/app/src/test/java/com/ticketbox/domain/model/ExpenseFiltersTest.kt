package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertEquals
import java.time.LocalDate
import java.time.ZoneOffset

class ExpenseFiltersTest {
    @Test
    fun filtersByExpenseTimeMonthAndCategory() {
        val items = listOf(
            expense(id = 1, category = "吃饭", expenseTime = "2026-05-03T04:20:00Z"),
            expense(id = 2, category = "交通", expenseTime = "2026-05-04T04:20:00Z"),
            expense(id = 3, category = "吃饭", expenseTime = "2026-06-03T04:20:00Z"),
        )

        val filtered = filterConfirmedExpenses(items, month = "2026-05", category = "吃饭")

        assertEquals(listOf(1L), filtered.map { it.id })
    }

    @Test
    fun fallsBackToConfirmedAtWhenExpenseTimeIsBlank() {
        val items = listOf(
            expense(id = 1, category = "购物", expenseTime = null, confirmedAt = "2026-05-03T04:20:00Z"),
            expense(id = 2, category = "购物", expenseTime = null, confirmedAt = "2026-04-03T04:20:00Z"),
        )

        val filtered = filterConfirmedExpenses(items, month = "2026-05", category = "")

        assertEquals(listOf(1L), filtered.map { it.id })
    }

    @Test
    fun buildsSevenDayTrendUsingExpenseTimeFallback() {
        val items = listOf(
            expense(id = 1, category = "吃饭", expenseTime = "2026-05-03T04:20:00Z", amountCents = 1200),
            expense(id = 2, category = "交通", expenseTime = null, confirmedAt = "2026-05-04T04:20:00Z", amountCents = 2300),
            expense(id = 3, category = "购物", expenseTime = "2026-04-28T04:20:00Z", amountCents = 9900),
        )

        val trend = recentDailySpending(
            expenses = items,
            referenceDate = LocalDate.parse("2026-05-04"),
            zoneId = ZoneOffset.UTC,
        )

        assertEquals(7, trend.size)
        assertEquals("2026-04-28", trend.first().date)
        assertEquals(9900, trend.first().amountCents)
        assertEquals(1200, trend[5].amountCents)
        assertEquals(2300, trend[6].amountCents)
    }

    @Test
    fun buildsMonthComparisonUsingLocalCache() {
        val items = listOf(
            expense(id = 1, category = "吃饭", expenseTime = "2026-05-03T04:20:00Z", amountCents = 1200),
            expense(id = 2, category = "交通", expenseTime = null, confirmedAt = "2026-05-04T04:20:00Z", amountCents = 2300),
            expense(id = 3, category = "购物", expenseTime = "2026-04-28T04:20:00Z", amountCents = 2000),
            expense(id = 4, category = "购物", expenseTime = "2026-03-28T04:20:00Z", amountCents = 9900),
        )

        val comparison = monthlySpendingComparison(
            expenses = items,
            month = "2026-05",
            zoneId = ZoneOffset.UTC,
        )

        checkNotNull(comparison)
        assertEquals("2026-05", comparison.currentMonth)
        assertEquals("2026-04", comparison.previousMonth)
        assertEquals(3500, comparison.currentAmountCents)
        assertEquals(2000, comparison.previousAmountCents)
        assertEquals(1500, comparison.deltaAmountCents)
        assertEquals(75, comparison.percentChange)
    }

    @Test
    fun skipsMonthComparisonWhenMonthIsBlankOrInvalid() {
        assertEquals(null, monthlySpendingComparison(emptyList(), ""))
        assertEquals(null, monthlySpendingComparison(emptyList(), "全部月份"))
    }

    private fun expense(
        id: Long,
        category: String,
        expenseTime: String?,
        confirmedAt: String? = "2026-05-03T04:20:00Z",
        amountCents: Long? = 100,
    ): Expense {
        return Expense(
            id = id,
            amountCents = amountCents,
            merchant = "测试商家",
            category = category,
            note = null,
            source = "iPhone截图",
            imagePath = null,
            thumbnailPath = null,
            imageHash = null,
            rawText = null,
            confidence = null,
            duplicateStatus = "none",
            duplicateOfId = null,
            duplicateReason = null,
            tags = null,
            valueScore = null,
            regretScore = null,
            status = "confirmed",
            expenseTime = expenseTime,
            createdAt = "2026-05-01T00:00:00Z",
            updatedAt = "2026-05-01T00:00:00Z",
            confirmedAt = confirmedAt,
            rejectedAt = null,
        )
    }
}

package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertEquals
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZoneOffset

class ExpenseFiltersTest {
    @Test
    fun filtersByExpenseTimeMonthAndCategory() {
        val items = listOf(
            expense(id = 1, category = "餐饮", expenseTime = "2026-05-03T04:20:00Z"),
            expense(id = 2, category = "交通", expenseTime = "2026-05-04T04:20:00Z"),
            expense(id = 3, category = "餐饮", expenseTime = "2026-06-03T04:20:00Z"),
        )

        val filtered = filterConfirmedExpenses(items, month = "2026-05", category = "餐饮")

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
    fun filtersLedgerMonthUsingLocalTimezone() {
        val items = listOf(
            expense(id = 1, category = "餐饮", expenseTime = "2026-04-30T16:30:00Z"),
            expense(id = 2, category = "餐饮", expenseTime = "2026-04-30T15:30:00Z"),
        )

        val filtered = filterConfirmedExpenses(
            expenses = items,
            month = "2026-05",
            category = "",
            zoneId = ZoneId.of("Asia/Shanghai"),
        )

        assertEquals(listOf(1L), filtered.map { it.id })
    }

    @Test
    fun invalidLedgerMonthMatchesNothing() {
        val items = listOf(
            expense(id = 1, category = "餐饮", expenseTime = "2026-05-03T04:20:00Z"),
        )

        val filtered = filterConfirmedExpenses(items, month = "2026-13", category = "")

        assertEquals(emptyList(), filtered.map { it.id })
    }

    @Test
    fun filtersByMerchantNoteTagsAndSourceQuery() {
        val items = listOf(
            expense(id = 1, category = "餐饮", expenseTime = "2026-05-03T04:20:00Z", merchant = "美团外卖"),
            expense(id = 2, category = "交通", expenseTime = "2026-05-03T04:20:00Z", note = "地铁通勤"),
            expense(id = 3, category = "购物", expenseTime = "2026-05-03T04:20:00Z", tags = "真香"),
            expense(id = 4, category = "其他", expenseTime = "2026-05-03T04:20:00Z", source = "手动记账"),
        )

        assertEquals(listOf(1L), filterConfirmedExpenses(items, month = "2026-05", category = "", query = "美团").map { it.id })
        assertEquals(listOf(2L), filterConfirmedExpenses(items, month = "2026-05", category = "", query = "通勤").map { it.id })
        assertEquals(listOf(3L), filterConfirmedExpenses(items, month = "2026-05", category = "", query = "真香").map { it.id })
        assertEquals(listOf(4L), filterConfirmedExpenses(items, month = "2026-05", category = "", query = "手动").map { it.id })
    }

    @Test
    fun buildsSevenDayTrendUsingExpenseTimeFallback() {
        val items = listOf(
            expense(id = 1, category = "餐饮", expenseTime = "2026-05-03T04:20:00Z", amountCents = 1200),
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
            expense(id = 1, category = "餐饮", expenseTime = "2026-05-03T04:20:00Z", amountCents = 1200),
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

    @Test
    fun buildsBudgetProgressAndCapsProgressBar() {
        val progress = monthlyBudgetProgress(
            stats = MonthlyStats(
                month = "2026-05",
                totalAmountCents = 12_000,
                count = 3,
                byCategory = emptyList(),
            ),
            budgetCents = 10_000,
        )

        checkNotNull(progress)
        assertEquals("2026-05", progress.month)
        assertEquals(10_000, progress.budgetCents)
        assertEquals(12_000, progress.spentCents)
        assertEquals(-2_000, progress.remainingCents)
        assertEquals(1.0f, progress.progress)
        assertEquals(120, progress.percent)
        assertEquals(true, progress.overBudget)
    }

    @Test
    fun skipsBudgetProgressWithoutPositiveBudget() {
        val stats = MonthlyStats(
            month = "2026-05",
            totalAmountCents = 1_000,
            count = 1,
            byCategory = emptyList(),
        )

        assertEquals(null, monthlyBudgetProgress(stats, null))
        assertEquals(null, monthlyBudgetProgress(stats, 0))
    }

    @Test
    fun buildsCategoryInsightAndSkipsZeroCategories() {
        val insight = monthlyCategoryInsight(
            MonthlyStats(
                month = "2026-05",
                totalAmountCents = 10_000,
                count = 4,
                byCategory = listOf(
                    CategoryStats(category = "餐饮", amountCents = 7_000, count = 3),
                    CategoryStats(category = "交通", amountCents = 3_000, count = 1),
                    CategoryStats(category = "游戏", amountCents = 0, count = 0),
                ),
            ),
        )

        checkNotNull(insight)
        assertEquals("餐饮", insight.topCategory)
        assertEquals(70, insight.topSharePercent)
        assertEquals(2_500, insight.averagePerExpenseCents)
        assertEquals(2, insight.categoryCount)
        assertEquals(true, insight.isConcentrated)
    }

    @Test
    fun skipsCategoryInsightWithoutRealSpending() {
        assertEquals(
            null,
            monthlyCategoryInsight(
                MonthlyStats(
                    month = "2026-05",
                    totalAmountCents = 0,
                    count = 0,
                    byCategory = listOf(CategoryStats(category = "其他", amountCents = 0, count = 0)),
                ),
            ),
        )
    }

    private fun expense(
        id: Long,
        category: String,
        expenseTime: String?,
        confirmedAt: String? = "2026-05-03T04:20:00Z",
        amountCents: Long? = 100,
        merchant: String? = "测试商家",
        note: String? = null,
        tags: String? = null,
        source: String = "iPhone截图",
    ): Expense {
        return Expense(
            id = id,
            publicId = "test-$id",
            amountCents = amountCents,
            merchant = merchant,
            category = category,
            note = note,
            source = source,
            imagePath = null,
            thumbnailPath = null,
            imageHash = null,
            rawText = null,
            confidence = null,
            duplicateStatus = "none",
            duplicateOfId = null,
            duplicateReason = null,
            tags = tags,
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

package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZoneOffset
import java.util.TimeZone

class ExpenseFiltersTest {
    @Test
    fun filtersByExpenseTimeMonthAndCategory() {
        val items = listOf(
            expense(id = 1, category = "餐饮", expenseTime = "2026-05-03T04:20:00Z"),
            expense(id = 2, category = "交通", expenseTime = "2026-05-04T04:20:00Z"),
            expense(id = 3, category = "餐饮", expenseTime = "2026-06-03T04:20:00Z"),
        )

        val filtered = filterConfirmedExpenses(
            items,
            ExpenseFilterCriteria(month = "2026-05", category = "餐饮"),
        )

        assertEquals(listOf(1L), filtered.map { it.id })
    }

    @Test
    fun fallsBackToConfirmedAtWhenExpenseTimeIsBlank() {
        val items = listOf(
            expense(id = 1, category = "购物", expenseTime = null, details = FixtureDetails(confirmedAt = "2026-05-03T04:20:00Z")),
            expense(id = 2, category = "购物", expenseTime = null, details = FixtureDetails(confirmedAt = "2026-04-03T04:20:00Z")),
        )

        val filtered = filterConfirmedExpenses(
            items,
            ExpenseFilterCriteria(month = "2026-05"),
        )

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
            criteria = ExpenseFilterCriteria(
                month = "2026-05",
                zoneId = ZoneId.of("Asia/Shanghai"),
            ),
        )

        assertEquals(listOf(1L), filtered.map { it.id })
    }

    @Test
    fun defaultLedgerMonthUsesPhoneSystemTimezone() {
        val previous = TimeZone.getDefault()
        try {
            TimeZone.setDefault(TimeZone.getTimeZone("Asia/Shanghai"))
            val items = listOf(
                expense(id = 1, category = "餐饮", expenseTime = "2026-04-30T16:30:00Z"),
                expense(id = 2, category = "餐饮", expenseTime = "2026-04-30T15:30:00Z"),
            )

            val filtered = filterConfirmedExpenses(
                items,
                ExpenseFilterCriteria(month = "2026-05"),
            )

            assertEquals(listOf(1L), filtered.map { it.id })
            assertEquals("2026-05", expenseLedgerMonth(items.first()))
        } finally {
            TimeZone.setDefault(previous)
        }
    }

    @Test
    fun offlineRoomFilterMatchesBackendMonthAcrossYearBoundary() {
        val items = listOf(
            expense(id = 1, category = "餐饮", expenseTime = "2026-12-31T16:30:00Z", amountCents = 1200),
            expense(id = 2, category = "餐饮", expenseTime = "2026-12-31T15:30:00Z", amountCents = 2300),
            expense(id = 3, category = "交通", expenseTime = "2026-12-31T16:40:00Z", amountCents = 3400),
        )
        val zone = ZoneId.of("Asia/Shanghai")

        val januaryFood = filterConfirmedExpenses(
            expenses = items,
            criteria = ExpenseFilterCriteria(
                month = "2027-01",
                category = "餐饮",
                zoneId = zone,
            ),
        )
        val decemberFood = filterConfirmedExpenses(
            expenses = items,
            criteria = ExpenseFilterCriteria(
                month = "2026-12",
                category = "餐饮",
                zoneId = zone,
            ),
        )
        val januaryStats = monthlyStatsFromConfirmedExpenses(
            expenses = items,
            month = "2027-01",
            zoneId = zone,
        )

        assertEquals(listOf(1L), januaryFood.map { it.id })
        assertEquals(listOf(2L), decemberFood.map { it.id })
        checkNotNull(januaryStats)
        assertEquals(4600, januaryStats.totalAmountCents)
        assertEquals(2, januaryStats.count)
    }

    @Test
    fun monthlyStatsFallbackUsesConfirmedAtAtLocalMonthBoundary() {
        val items = listOf(
            expense(id = 1, category = "餐饮", expenseTime = null, amountCents = 1200, details = FixtureDetails(confirmedAt = "2026-04-30T16:30:00Z")),
            expense(id = 2, category = "餐饮", expenseTime = null, amountCents = 2300, details = FixtureDetails(confirmedAt = "2026-04-30T15:30:00Z")),
            expense(id = 3, category = "交通", expenseTime = null, amountCents = 3400, details = FixtureDetails(confirmedAt = "2026-04-30T16:40:00Z")),
        )
        val zone = ZoneId.of("Asia/Shanghai")

        val mayFood = filterConfirmedExpenses(
            expenses = items,
            criteria = ExpenseFilterCriteria(
                month = "2026-05",
                category = "餐饮",
                zoneId = zone,
            ),
        )
        val mayStats = monthlyStatsFromConfirmedExpenses(
            expenses = items,
            month = "2026-05",
            zoneId = zone,
        )

        assertEquals(listOf(1L), mayFood.map { it.id })
        checkNotNull(mayStats)
        assertEquals(4600, mayStats.totalAmountCents)
        assertEquals(2, mayStats.count)
    }

    @Test
    fun expenseLedgerMonthUsesLocalMonthAndFallbackOrder() {
        val zone = ZoneId.of("Asia/Shanghai")

        assertEquals(
            "2026-05",
            expenseLedgerMonth(
                expense(id = 1, category = "餐饮", expenseTime = "2026-04-30T16:30:00Z"),
                zoneId = zone,
            ),
        )
        assertEquals(
            "2026-05",
            expenseLedgerMonth(
                expense(id = 2, category = "餐饮", expenseTime = null, details = FixtureDetails(confirmedAt = "2026-04-30T16:30:00Z")),
                zoneId = zone,
            ),
        )
        assertEquals(
            "2027-01",
            expenseLedgerMonth(
                expense(id = 3, category = "餐饮", expenseTime = "2026-12-31T16:30:00Z"),
                zoneId = zone,
            ),
        )
    }

    @Test
    fun invalidLedgerMonthMatchesNothing() {
        val items = listOf(
            expense(id = 1, category = "餐饮", expenseTime = "2026-05-03T04:20:00Z"),
        )

        val filtered = filterConfirmedExpenses(
            items,
            ExpenseFilterCriteria(month = "2026-13"),
        )

        assertEquals(emptyList(), filtered.map { it.id })
    }

    @Test
    fun filtersByMerchantNoteTagsAndSourceQuery() {
        val items = listOf(
            expense(id = 1, category = "餐饮", expenseTime = "2026-05-03T04:20:00Z", details = FixtureDetails(merchant = "美团外卖")),
            expense(id = 2, category = "交通", expenseTime = "2026-05-03T04:20:00Z", details = FixtureDetails(note = "地铁通勤")),
            expense(id = 3, category = "购物", expenseTime = "2026-05-03T04:20:00Z", details = FixtureDetails(tags = "真香")),
            expense(id = 4, category = "其他", expenseTime = "2026-05-03T04:20:00Z", details = FixtureDetails(source = "手动记账")),
        )

        assertEquals(
            listOf(1L),
            filterConfirmedExpenses(
                items,
                ExpenseFilterCriteria(month = "2026-05", query = "美团"),
            ).map { it.id },
        )
        assertEquals(
            listOf(2L),
            filterConfirmedExpenses(
                items,
                ExpenseFilterCriteria(month = "2026-05", query = "通勤"),
            ).map { it.id },
        )
        assertEquals(
            listOf(3L),
            filterConfirmedExpenses(
                items,
                ExpenseFilterCriteria(month = "2026-05", query = "真香"),
            ).map { it.id },
        )
        assertEquals(
            listOf(4L),
            filterConfirmedExpenses(
                items,
                ExpenseFilterCriteria(month = "2026-05", query = "手动"),
            ).map { it.id },
        )
    }

    @Test
    fun filtersByExactNormalizedTag() {
        val items = listOf(
            expense(id = 1, category = "餐饮", expenseTime = "2026-05-03T04:20:00Z", details = FixtureDetails(tags = " 周末 ，AI")),
            expense(id = 2, category = "购物", expenseTime = "2026-05-04T04:20:00Z", details = FixtureDetails(tags = "周末采购")),
            expense(id = 3, category = "交通", expenseTime = "2026-05-05T04:20:00Z", details = FixtureDetails(tags = "ai")),
        )

        assertEquals(
            listOf(1L),
            filterConfirmedExpenses(
                items,
                ExpenseFilterCriteria(month = "2026-05", tag = "周末"),
            ).map { it.id },
        )
        assertEquals(
            listOf(1L, 3L),
            filterConfirmedExpenses(
                items,
                ExpenseFilterCriteria(month = "2026-05", tag = "AI"),
            ).map { it.id },
        )
    }

    @Test
    fun buildsSevenDayTrendUsingExpenseTimeFallback() {
        val items = listOf(
            expense(id = 1, category = "餐饮", expenseTime = "2026-05-03T04:20:00Z", amountCents = 1200),
            expense(id = 2, category = "交通", expenseTime = null, amountCents = 2300, details = FixtureDetails(confirmedAt = "2026-05-04T04:20:00Z")),
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
            expense(id = 2, category = "交通", expenseTime = null, amountCents = 2300, details = FixtureDetails(confirmedAt = "2026-05-04T04:20:00Z")),
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
    fun recentMerchantsAreNewestFirstDedupedAndCarryLastCategory() {
        val items = listOf(
            expense(id = 1, category = "餐饮", expenseTime = "2026-05-01T04:00:00Z", details = FixtureDetails(merchant = "早餐店")),
            expense(id = 2, category = "交通", expenseTime = "2026-05-05T04:00:00Z", details = FixtureDetails(merchant = "地铁")),
            // Same merchant as #1 but more recent AND a different category — the
            // newest occurrence must win the slot and supply the category.
            expense(id = 3, category = "夜宵", expenseTime = "2026-05-06T04:00:00Z", details = FixtureDetails(merchant = "早餐店")),
        )

        val recent = recentLedgerMerchants(items)

        assertEquals(
            listOf(
                RecentMerchant(merchant = "早餐店", category = "夜宵"),
                RecentMerchant(merchant = "地铁", category = "交通"),
            ),
            recent,
        )
    }

    @Test
    fun recentMerchantsSkipBlankMerchantsAndRespectLimit() {
        val items = listOf(
            expense(id = 1, category = "餐饮", expenseTime = "2026-05-01T04:00:00Z", details = FixtureDetails(merchant = "A")),
            expense(id = 2, category = "餐饮", expenseTime = "2026-05-02T04:00:00Z", details = FixtureDetails(merchant = "  ")),
            expense(id = 3, category = "餐饮", expenseTime = "2026-05-03T04:00:00Z", details = FixtureDetails(merchant = null)),
            expense(id = 4, category = "餐饮", expenseTime = "2026-05-04T04:00:00Z", details = FixtureDetails(merchant = "B")),
            expense(id = 5, category = "餐饮", expenseTime = "2026-05-05T04:00:00Z", details = FixtureDetails(merchant = "C")),
        )

        // Blank/null merchants drop out; limit caps the list (newest first).
        assertEquals(
            listOf("C", "B"),
            recentLedgerMerchants(items, limit = 2).map { it.merchant },
        )
        assertEquals(emptyList(), recentLedgerMerchants(items, limit = 0))
    }

    @Test
    fun recentMerchantsFallBackToConfirmedAtForRecency() {
        val items = listOf(
            expense(id = 1, category = "餐饮", expenseTime = null, details = FixtureDetails(confirmedAt = "2026-05-01T04:00:00Z", merchant = "旧店")),
            expense(id = 2, category = "交通", expenseTime = null, details = FixtureDetails(confirmedAt = "2026-05-09T04:00:00Z", merchant = "新店")),
        )

        assertEquals(
            listOf("新店", "旧店"),
            recentLedgerMerchants(items).map { it.merchant },
        )
    }

    @Test
    fun shiftLedgerMonthStepsAcrossYearBoundaryAndRejectsNonMonths() {
        assertEquals("2026-04", shiftLedgerMonth("2026-05", -1L))
        assertEquals("2026-06", shiftLedgerMonth("2026-05", 1L))
        assertEquals("2025-12", shiftLedgerMonth("2026-01", -1L))
        assertEquals("2027-01", shiftLedgerMonth("2026-12", 1L))
        assertEquals(null, shiftLedgerMonth("", -1L))
        assertEquals(null, shiftLedgerMonth("全部月份", 1L))
        assertEquals(null, shiftLedgerMonth("2026-13", 1L))
    }

    @Test
    fun buildsMonthlyStatsFromLocalConfirmedCache() {
        val items = listOf(
            expense(id = 1, category = "餐饮", expenseTime = "2026-05-03T04:20:00Z", amountCents = 1200, details = FixtureDetails(tags = "真香，AI，真香")),
            expense(id = 2, category = "餐饮", expenseTime = null, amountCents = 2300, details = FixtureDetails(confirmedAt = "2026-05-04T04:20:00Z")),
            expense(id = 3, category = "购物", expenseTime = "2026-05-05T04:20:00Z", amountCents = 9900, details = FixtureDetails(tags = "必要")),
            expense(id = 4, category = "交通", expenseTime = "2026-04-30T04:20:00Z", amountCents = 400),
        )

        val stats = monthlyStatsFromConfirmedExpenses(
            expenses = items,
            month = "2026-05",
            zoneId = ZoneOffset.UTC,
        )

        checkNotNull(stats)
        assertEquals("2026-05", stats.month)
        assertEquals(13_400, stats.totalAmountCents)
        assertEquals(3, stats.count)
        assertEquals(
            listOf(
                CategoryStats(category = "购物", amountCents = 9_900, count = 1),
                CategoryStats(category = "餐饮", amountCents = 3_500, count = 2),
            ),
            stats.byCategory,
        )
        assertEquals(
            listOf(
                TagStats(tag = "必要", amountCents = 9_900, count = 1),
                TagStats(tag = "真香", amountCents = 1_200, count = 1),
                TagStats(tag = "AI", amountCents = 1_200, count = 1),
            ),
            stats.byTag,
        )

        val tagStats = monthlyStatsFromConfirmedExpenses(
            expenses = items,
            month = "2026-05",
            tag = "真香",
            zoneId = ZoneOffset.UTC,
        )

        checkNotNull(tagStats)
        assertEquals(1_200, tagStats.totalAmountCents)
        assertEquals(1, tagStats.count)
        assertEquals(
            listOf(
                TagStats(tag = "真香", amountCents = 1_200, count = 1),
                TagStats(tag = "AI", amountCents = 1_200, count = 1),
            ),
            tagStats.byTag,
        )
    }

    @Test
    fun skipsMonthlyStatsFallbackWhenNoLocalSpending() {
        val items = listOf(
            expense(id = 1, category = "餐饮", expenseTime = "2026-04-03T04:20:00Z", amountCents = 1200),
            expense(id = 2, category = "餐饮", expenseTime = "2026-05-03T04:20:00Z", amountCents = null),
        )

        assertEquals(
            null,
            monthlyStatsFromConfirmedExpenses(
                expenses = items,
                month = "2026-05",
                zoneId = ZoneOffset.UTC,
            ),
        )
        assertEquals(null, monthlyStatsFromConfirmedExpenses(items, month = "not-a-month"))
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

    @Test
    fun parsesSearchAmountToCentsWithBoundaryRules() {
        // Whole yuan, one decimal, currency-symbol + two decimals all parse.
        assertEquals(1_200L, parseSearchAmountCents("12"))
        assertEquals(1_250L, parseSearchAmountCents("12.5"))
        assertEquals(1_250L, parseSearchAmountCents("¥12.50"))
        assertEquals(1_250L, parseSearchAmountCents("￥12.5"))
        assertEquals(12_800L, parseSearchAmountCents("128"))
        assertEquals(128_000L, parseSearchAmountCents("1,280"))
        assertEquals(0L, parseSearchAmountCents("0"))
        // More than two fraction digits is rejected (no silent rounding).
        assertNull(parseSearchAmountCents("12.345"))
        // Non-numeric / blank / negative do not parse to an amount.
        assertNull(parseSearchAmountCents("咖啡"))
        assertNull(parseSearchAmountCents("12a"))
        assertNull(parseSearchAmountCents("   "))
        assertNull(parseSearchAmountCents("-12"))
    }

    @Test
    fun parsesSearchAmountInHomeCurrencyMinorDigits() {
        // 零小数 home（JPY/KRW）："1200" 是 minor 1200，不再扩成 120000 ——
        // 这是 JPY 用户按金额搜索命中 originalAmountMinor/home 腿的前提。
        assertEquals(1_200L, parseSearchAmountCents("1200", CurrencyCode.JPY))
        assertEquals(1_200L, parseSearchAmountCents("¥1200", CurrencyCode.JPY))
        assertEquals(0L, parseSearchAmountCents("0", CurrencyCode.KRW))
        // 零小数币种带小数部分 → 不解析为金额（落回文本匹配），不静默进位。
        assertNull(parseSearchAmountCents("1200.5", CurrencyCode.JPY))
        assertNull(parseSearchAmountCents("12.0", CurrencyCode.KRW))
        // 2 位小数 home 显式传参时与默认口径一致。
        assertEquals(1_250L, parseSearchAmountCents("12.5", CurrencyCode.USD))
    }

    @Test
    fun expenseMatchesAmountOnHomeOrOriginalLeg() {
        val homeLeg = expense(id = 1, category = "餐饮", expenseTime = null, amountCents = 1_250)
        val foreignLeg = expense(id = 2, category = "餐饮", expenseTime = null, amountCents = 9_900)
            .copy(originalAmountMinor = 1_250)

        assertTrue(expenseMatchesAmountCents(homeLeg, 1_250))
        assertTrue(expenseMatchesAmountCents(foreignLeg, 1_250))
        assertFalse(expenseMatchesAmountCents(homeLeg, 800))
    }

    @Test
    fun parsesSearchAmountAcceptsDisplayedValuesAcrossCurrencies() {
        // PR#255 P2-1：从 Android 自己的格式化器（formatAmount，localeTag 同款
        // DecimalFormatSymbols）复制的显示值，按所选币种归一化符号与分隔符后必须可解析。
        assertEquals(1_200L, parseSearchAmountCents("₩1,200", CurrencyCode.KRW))
        assertEquals(123_450L, parseSearchAmountCents("HK$1,234.50", CurrencyCode.HKD))
        assertEquals(123_450L, parseSearchAmountCents("£1,234.50", CurrencyCode.GBP))
        // de-DE：点分组、逗号小数。
        assertEquals(123_450L, parseSearchAmountCents("€1.234,50", CurrencyCode.EUR))
        // EUR 无符号逗号小数不得误读为分组（旧实现读出 1,250 倍值）。
        assertEquals(1_250L, parseSearchAmountCents("12,50", CurrencyCode.EUR))
        // de-DE 用户手输点号 "12.50"：非合法分组形态（尾组 2 位），按小数对待而非放大。
        assertEquals(1_250L, parseSearchAmountCents("12.50", CurrencyCode.EUR))
        // EUR 合法点分组整体形态仍按分组剥离。
        assertEquals(123_400L, parseSearchAmountCents("1.234", CurrencyCode.EUR))
        // 零小数币种的带符号分组显示值。
        assertEquals(50_000L, parseSearchAmountCents("¥50,000", CurrencyCode.JPY))
        // 他币种符号不剥：HK$ 文本在 USD 腿上不可解析（防串币种假命中）。
        assertNull(parseSearchAmountCents("HK$1,234.50", CurrencyCode.USD))
        // 残留多小数点 / 字母仍拒。
        assertNull(parseSearchAmountCents("1.2.3", CurrencyCode.USD))
        assertNull(parseSearchAmountCents("12,50,30", CurrencyCode.EUR))
    }

    @Test
    fun expenseMatchesSearchAmountParsesEachLegInItsOwnCurrency() {
        // JPY-home、USD 原币：查 "12.50" 按 USD 解析原币腿命中（home 零小数解析不出，旧实现丢失）。
        val jpyHomeUsdOriginal = expense(id = 1, category = "餐饮", expenseTime = null, amountCents = 18_518)
            .copy(
                homeCurrency = CurrencyCode.JPY,
                originalCurrencyCode = CurrencyCode.USD,
                originalAmountMinor = 1_250,
            )
        assertTrue(expenseMatchesSearchAmount(jpyHomeUsdOriginal, "12.50"))
        // home 腿仍按 JPY：查 "18518" 命中 home minor。
        assertTrue(expenseMatchesSearchAmount(jpyHomeUsdOriginal, "18518"))
        // 反巧合：查 "1250" 不得撞上 USD minor 1250（跨 exponent 数值巧合，不是用户语义）。
        assertFalse(expenseMatchesSearchAmount(jpyHomeUsdOriginal, "1250"))

        // CNY-home、JPY 原币：查 "1200" 按 JPY 解析原币腿命中（旧实现解析成 120000 错配）。
        val cnyHomeJpyOriginal = expense(id = 2, category = "餐饮", expenseTime = null, amountCents = 5_500)
            .copy(
                originalCurrencyCode = CurrencyCode.JPY,
                originalAmountMinor = 1_200,
            )
        assertTrue(expenseMatchesSearchAmount(cnyHomeJpyOriginal, "1200"))
        assertTrue(expenseMatchesSearchAmount(cnyHomeJpyOriginal, "55"))

        // 同币种 legacy 行：original 腿与 home 共用一次解析，行为与 expenseMatchesAmountCents 一致。
        val sameCurrency = expense(id = 3, category = "餐饮", expenseTime = null, amountCents = 9_900)
            .copy(originalAmountMinor = 1_250)
        assertTrue(expenseMatchesSearchAmount(sameCurrency, "12.5"))
        assertFalse(expenseMatchesSearchAmount(sameCurrency, "12.345"))
    }

    @Test
    fun searchableMonthsAndCategoriesAreDerivedFromCaches() {
        val items = listOf(
            expense(id = 1, category = "餐饮", expenseTime = "2026-05-10T08:00:00Z"),
            expense(id = 2, category = "购物", expenseTime = "2026-06-10T08:00:00Z"),
            expense(id = 3, category = "餐饮", expenseTime = "2026-05-12T08:00:00Z"),
        )

        // Distinct months, newest first.
        assertEquals(listOf("2026-06", "2026-05"), searchableMonths(items, ZoneOffset.UTC))
        // Default catalog first, then any extras present (deduped).
        val categories = searchableCategories(items)
        assertEquals(DEFAULT_EXPENSE_CATEGORIES, categories)
        assertTrue("餐饮" in categories && "购物" in categories)
    }

    @Test
    fun appendRecentSearchDedupesCapsAndMovesToFront() {
        // Newest first; blank is a no-op.
        assertEquals(listOf("b", "a"), appendRecentSearch(listOf("a"), "b"))
        assertEquals(listOf("a"), appendRecentSearch(listOf("a"), "   "))
        // Case-insensitive de-dup moves the existing entry to the front.
        assertEquals(listOf("Cafe", "x"), appendRecentSearch(listOf("x", "cafe"), "Cafe"))
        // Cap enforced (oldest drops).
        assertEquals(
            listOf("9", "8", "7", "6", "5", "4", "3", "2"),
            appendRecentSearch(listOf("8", "7", "6", "5", "4", "3", "2", "1"), "9", max = 8),
        )
    }

    private data class FixtureDetails(
        val confirmedAt: String? = "2026-05-03T04:20:00Z",
        val merchant: String? = "测试商家",
        val note: String? = null,
        val tags: String? = null,
        val source: String = "iPhone截图",
    )

    private fun expense(
        id: Long,
        category: String,
        expenseTime: String?,
        amountCents: Long? = 100,
        details: FixtureDetails = FixtureDetails(),
    ): Expense {
        return Expense(
            id = id,
            publicId = "test-$id",
            amountCents = amountCents,
            merchant = details.merchant,
            category = category,
            note = details.note,
            source = details.source,
            imagePath = null,
            thumbnailPath = null,
            imageHash = null,
            rawText = null,
            confidence = null,
            duplicateStatus = "none",
            duplicateOfId = null,
            duplicateReason = null,
            tags = details.tags,
            valueScore = null,
            regretScore = null,
            status = "confirmed",
            expenseTime = expenseTime,
            createdAt = "2026-05-01T00:00:00Z",
            updatedAt = "2026-05-01T00:00:00Z",
            rowVersion = 1L,
            confirmedAt = details.confirmedAt,
            rejectedAt = null,
        )
    }
}

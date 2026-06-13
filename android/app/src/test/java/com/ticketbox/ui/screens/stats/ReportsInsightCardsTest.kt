package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.ReportCategoryComparison
import com.ticketbox.domain.model.ReportTrendPoint
import kotlin.test.Test
import kotlin.test.assertEquals

class ReportsInsightCardsTest {
    @Test
    fun trendChartPointsKeepServerOrderAndClampInvalidValues() {
        val points = reportTrendChartPoints(
            listOf(
                ReportTrendPoint(
                    bucket = "2026-05-01",
                    label = "05-01",
                    amountCents = 1_250L,
                    count = 1,
                ),
                ReportTrendPoint(
                    bucket = "2026-05-02",
                    label = "",
                    amountCents = -300L,
                    count = -1,
                ),
            ),
        )

        assertEquals(
            listOf(
                ReportTrendChartPoint(x = 0, label = "05-01", amountCents = 1_250L, count = 1),
                ReportTrendChartPoint(x = 1, label = "05-02", amountCents = 0L, count = 0),
            ),
            points,
        )
    }

    @Test
    fun compactAmountLabelsUseCentsWithoutFloatingPointMath() {
        assertEquals("¥0", compactAmountCentsLabel(0L))
        assertEquals("¥9.9", compactAmountCentsLabel(990L))
        assertEquals("¥1.2k", compactAmountCentsLabel(123_400L))
        assertEquals("¥1.2万", compactAmountCentsLabel(1_234_000L))
        assertEquals("-¥1.2万", compactAmountCentsLabel(-1_234_000L))
    }

    @Test
    fun comparisonChartRowsClampNegativesAndDropBothZeroRows() {
        // 轴3 双柱:负值钳零(图不画负柱);两月皆零的行剔除(画不出对比还占 x 位)。
        val rows = categoryComparisonChartRows(
            listOf(
                comparisonRow(category = "餐饮", amountCents = 1_200L, previousAmountCents = 900L),
                comparisonRow(category = "退款", amountCents = -500L, previousAmountCents = 0L),
                comparisonRow(category = "交通", amountCents = 0L, previousAmountCents = 800L),
            ),
        )
        assertEquals(
            listOf(
                CategoryComparisonChartRow("餐饮", 1_200L, 900L),
                CategoryComparisonChartRow("交通", 0L, 800L),
            ),
            rows,
        )
    }

    @Test
    fun comparisonChartRowsKeepOrderAndCapAtFive() {
        // 与行制 take(5) 同窗口:保服务端顺序取前 5。
        val rows = categoryComparisonChartRows(
            (1..7).map { index ->
                comparisonRow(category = "分类$index", amountCents = index * 100L, previousAmountCents = 0L)
            },
        )
        assertEquals(5, rows.size)
        assertEquals(listOf("分类1", "分类2", "分类3", "分类4", "分类5"), rows.map { it.category })
    }

    private fun comparisonRow(
        category: String,
        amountCents: Long,
        previousAmountCents: Long,
    ) = ReportCategoryComparison(
        category = category,
        amountCents = amountCents,
        count = 1,
        previousAmountCents = previousAmountCents,
        previousCount = 1,
        deltaAmountCents = amountCents - previousAmountCents,
        deltaCount = 0,
    )
}

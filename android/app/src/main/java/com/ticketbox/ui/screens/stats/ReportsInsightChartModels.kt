package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.ReportCategoryComparison
import com.ticketbox.domain.model.ReportTrendPoint
import java.math.BigDecimal
import java.math.RoundingMode
import kotlin.math.abs

internal data class ReportTrendChartPoint(
    val x: Int,
    val label: String,
    val amountCents: Long,
    val count: Int,
)

internal fun reportTrendChartPoints(trend: List<ReportTrendPoint>): List<ReportTrendChartPoint> =
    trend.mapIndexed { index, point ->
        ReportTrendChartPoint(
            x = index,
            label = point.label.ifBlank { point.bucket.takeLast(5) },
            amountCents = point.amountCents.coerceAtLeast(0L),
            count = point.count.coerceAtLeast(0),
        )
    }

internal data class CategoryComparisonChartRow(
    val category: String,
    val currentAmountCents: Long,
    val previousAmountCents: Long,
)

/**
 * 轴3 双柱对比的图数据(纯函数,单测直测):负值钳零(图不画负柱),
 * 两月皆零的行剔除(画不出对比还占一个 x 位);保序取前 5(与行制 take(5) 同窗口)。
 */
internal fun categoryComparisonChartRows(
    rows: List<ReportCategoryComparison>,
): List<CategoryComparisonChartRow> =
    rows.asSequence()
        .map { row ->
            CategoryComparisonChartRow(
                category = row.category,
                currentAmountCents = row.amountCents.coerceAtLeast(0L),
                previousAmountCents = row.previousAmountCents.coerceAtLeast(0L),
            )
        }
        .filter { it.currentAmountCents > 0L || it.previousAmountCents > 0L }
        .take(5)
        .toList()

internal fun compactAmountCentsLabel(amountCents: Long): String {
    val sign = if (amountCents < 0L) "-" else ""
    val absCents = abs(amountCents)
    return when {
        absCents >= 1_000_000L -> "${sign}¥${decimal(absCents, 1_000_000L)}万"
        absCents >= 100_000L -> "${sign}¥${decimal(absCents, 100_000L)}k"
        else -> "${sign}¥${decimal(absCents, 100L)}"
    }
}

private fun decimal(value: Long, divisor: Long): String =
    BigDecimal(value)
        .divide(BigDecimal(divisor), 1, RoundingMode.HALF_UP)
        .stripTrailingZeros()
        .toPlainString()

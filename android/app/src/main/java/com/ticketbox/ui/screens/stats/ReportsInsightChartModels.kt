package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.ReportCategoryComparison
import com.ticketbox.domain.model.ReportTrendPoint
import com.ticketbox.ui.components.formatDisplayAmount
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
    val yearOverYearAmountCents: Long,
    val hasPrevious: Boolean,
    val hasYearOverYear: Boolean,
)

/**
 * 轴3 对比图数据(纯函数,单测直测):负值钳零(图不画负柱);
 * 历史系列必须有后端 count 才可展示,避免把缺失历史样本画成 0 对比。
 */
internal fun categoryComparisonChartRows(
    rows: List<ReportCategoryComparison>,
): List<CategoryComparisonChartRow> =
    rows.asSequence()
        .map { row ->
            val hasPrevious = row.previousCount > 0
            val hasYearOverYear = row.yearOverYearCount > 0
            CategoryComparisonChartRow(
                category = row.category,
                currentAmountCents = row.amountCents.coerceAtLeast(0L),
                previousAmountCents = if (hasPrevious) row.previousAmountCents.coerceAtLeast(0L) else 0L,
                yearOverYearAmountCents = if (hasYearOverYear) row.yearOverYearAmountCents.coerceAtLeast(0L) else 0L,
                hasPrevious = hasPrevious,
                hasYearOverYear = hasYearOverYear,
            )
        }
        .filter {
            it.currentAmountCents > 0L ||
                it.hasPrevious ||
                it.hasYearOverYear
        }
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

// ── WCAG 1.1.1 图表文本替代(纯函数,单测直测)─────────────────────────────
// 自绘柱图对 TalkBack 仍是图形节点,给图表节点补 contentDescription 文本替代;
// 金额走与可见行同源的 formatDisplayAmount,屏幕阅读器听到的与屏上一致。

/** 趋势图文本替代:只逐档朗读「有支出」的档([listed],「，」相接),零额档并成 [zeroBuckets] 计数,
 *  由调用方汇总成「其余 N 档无支出」——避免日粒度下逐日朗读 ~30 个 ¥0.00(纯可用性,见复审 P3)。 */
internal data class TrendChartA11y(val listed: String, val zeroBuckets: Int)

internal fun trendChartA11y(
    points: List<ReportTrendChartPoint>,
    currencyDisplay: CurrencyDisplay,
): TrendChartA11y {
    val nonZero = points.filter { it.amountCents > 0L }
    return TrendChartA11y(
        listed = nonZero.joinToString("，") { "${it.label} ${formatDisplayAmount(it.amountCents, currencyDisplay)}" },
        zeroBuckets = points.size - nonZero.size,
    )
}

/** 对比图文本替代 body:只拼接后端确认存在的历史系列,避免把缺失历史样本读成 ¥0.00。 */
internal fun comparisonChartA11yBody(
    rows: List<CategoryComparisonChartRow>,
    currentMonthLabel: String,
    previousMonthLabel: String,
    yearOverYearLabel: String,
    currencyDisplay: CurrencyDisplay,
): String =
    rows.joinToString("；") {
        buildList {
            add("${it.category} $currentMonthLabel ${formatDisplayAmount(it.currentAmountCents, currencyDisplay)}")
            if (it.hasPrevious) {
                add("$previousMonthLabel ${formatDisplayAmount(it.previousAmountCents, currencyDisplay)}")
            }
            if (it.hasYearOverYear) {
                add("$yearOverYearLabel ${formatDisplayAmount(it.yearOverYearAmountCents, currencyDisplay)}")
            }
        }.joinToString(" ")
    }

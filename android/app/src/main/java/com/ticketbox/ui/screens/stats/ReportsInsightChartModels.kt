package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.ReportCategoryComparison
import com.ticketbox.domain.model.ReportTrendPoint
import com.ticketbox.ui.components.formatAmount
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

// ── WCAG 1.1.1 图表文本替代(纯函数,单测直测)─────────────────────────────
// Vico 柱图对 TalkBack 是不透明画布,给图表节点补 contentDescription 文本替代;
// 金额走与可见行同源的 formatAmount,屏幕阅读器听到的与屏上一致。

/** 趋势图文本替代:只逐档朗读「有支出」的档([listed],「，」相接),零额档并成 [zeroBuckets] 计数,
 *  由调用方汇总成「其余 N 档无支出」——避免日粒度下逐日朗读 ~30 个 ¥0.00(纯可用性,见复审 P3)。 */
internal data class TrendChartA11y(val listed: String, val zeroBuckets: Int)

internal fun trendChartA11y(points: List<ReportTrendChartPoint>): TrendChartA11y {
    val nonZero = points.filter { it.amountCents > 0L }
    return TrendChartA11y(
        listed = nonZero.joinToString("，") { "${it.label} ${formatAmount(it.amountCents)}" },
        zeroBuckets = points.size - nonZero.size,
    )
}

/** 双柱对比图文本替代 body:逐分类「分类 本月X 上月Y」以「；」相接;月份标签由调用方传入资源串
 *  ([currentMonthLabel]/[previousMonthLabel] 复用图例同源串)。图数据已过滤两月皆零,无需再滤。 */
internal fun comparisonChartA11yBody(
    rows: List<CategoryComparisonChartRow>,
    currentMonthLabel: String,
    previousMonthLabel: String,
): String =
    rows.joinToString("；") {
        "${it.category} $currentMonthLabel ${formatAmount(it.currentAmountCents)} " +
            "$previousMonthLabel ${formatAmount(it.previousAmountCents)}"
    }

package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.AppEndAlignedAmountText
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalChartTokens
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalStatsTokens
import com.ticketbox.ui.design.StatsComparisonChartTokens
import com.ticketbox.ui.design.tabularNum
import kotlin.math.max

@Composable
internal fun ReportsTrendFlowChart(points: List<ReportTrendChartPoint>) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val summary = remember(points) { reportsTrendEvidence(points) }
    val chartPoints = remember(points) {
        points.map { point ->
            StatsSpendChartPoint(label = point.label, amountCents = point.amountCents)
        }
    }
    val visibleChartPoints = rememberSpendWindowChartPoints(points = chartPoints, maxWindows = 7)
    val trendA11yData = remember(points, currencyDisplay) { trendChartA11y(points, currencyDisplay) }
    val trendA11y = if (trendA11yData.zeroBuckets > 0) {
        stringResource(R.string.stats_reports_chart_a11y_with_zeros, trendA11yData.listed, trendA11yData.zeroBuckets)
    } else {
        stringResource(R.string.stats_reports_chart_a11y, trendA11yData.listed)
    }

    Column(
        modifier = Modifier.fillMaxWidth().semantics { contentDescription = trendA11y },
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        ReportsTrendChartSummary(summary = summary)
        ReportsTrendFactStrip(summary = summary)
        if (summary.shouldUseDominanceBreakdown) {
            ReportsTrendDominanceBreakdown(summary = summary)
        } else {
            StatsSpendTrendChart(
                points = visibleChartPoints,
                contentDescription = trendA11y,
            )
        }
    }
}

@Composable
private fun ReportsTrendChartSummary(
    summary: ReportsTrendEvidence,
) {
    summary.peak?.takeIf { it.amountCents > 0L }?.let {
        Text(
            text = if (summary.shouldUseDominanceBreakdown) {
                stringResource(
                    R.string.stats_reports_chart_takeaway_concentrated,
                    it.label,
                    summary.peakSharePercent,
                )
            } else {
                stringResource(
                    R.string.stats_reports_chart_takeaway_spread,
                    summary.positiveBucketCount,
                    summary.peakSharePercent,
                )
            },
            color = MaterialTheme.colorScheme.primary,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Text(
                text = stringResource(R.string.stats_reports_chart_peak, it.label),
                modifier = Modifier.weight(1f),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelSmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            AppEndAlignedAmountText(
                text = formatDisplayAmount(it.amountCents, LocalCurrencyDisplay.current),
                modifier = Modifier.weight(0.8f),
                role = AppAmountRole.Compact,
            )
        }
        Text(
            text = stringResource(
                R.string.stats_reports_chart_distribution_hint,
                summary.peakSharePercent,
                formatDisplayAmount(summary.otherAverageAmountCents, LocalCurrencyDisplay.current),
            ),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
        )
    }
}

@Composable
private fun ReportsTrendFactStrip(summary: ReportsTrendEvidence) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        ReportsTrendFact(
            label = stringResource(R.string.stats_reports_chart_active_days),
            value = stringResource(R.string.stats_reports_chart_active_days_value, summary.positiveBucketCount),
            modifier = Modifier.weight(1f),
        )
        ReportsTrendFact(
            label = stringResource(R.string.stats_reports_chart_peak_share_label),
            value = stringResource(R.string.stats_reports_chart_peak_share_value, summary.peakSharePercent),
            modifier = Modifier.weight(1f),
        )
        ReportsTrendFact(
            label = stringResource(R.string.stats_reports_chart_other_average_label),
            value = formatDisplayAmount(summary.otherAverageAmountCents, LocalCurrencyDisplay.current),
            isAmount = true,
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun ReportsTrendFact(
    label: String,
    value: String,
    isAmount: Boolean = false,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        if (isAmount) {
            AppAmountText(
                text = value,
                role = AppAmountRole.Compact,
            )
        } else {
            Text(
                text = value,
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.bodyMedium.tabularNum(),
                fontWeight = AppTextHierarchy.body.weight,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun ReportsTrendDominanceBreakdown(summary: ReportsTrendEvidence) {
    val currencyDisplay = LocalCurrencyDisplay.current
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        summary.peak?.takeIf { it.amountCents > 0L }?.let { peak ->
            ReportsTrendBreakdownRow(
                label = stringResource(R.string.stats_reports_chart_peak, peak.label),
                amountCents = peak.amountCents,
                currencyDisplay = currencyDisplay,
            )
        }
        if (summary.otherPositiveBucketCount > 0) {
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = 0.16f))
            ReportsTrendBreakdownRow(
                label = stringResource(R.string.stats_reports_chart_other_total, summary.otherPositiveBucketCount),
                amountCents = summary.otherTotalAmountCents,
                currencyDisplay = currencyDisplay,
            )
        }
    }
}

@Composable
private fun ReportsTrendBreakdownRow(
    label: String,
    amountCents: Long,
    currencyDisplay: CurrencyDisplay,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Text(
            text = label,
            modifier = Modifier.weight(1f),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        AppEndAlignedAmountText(
            text = formatDisplayAmount(amountCents, currencyDisplay),
            modifier = Modifier.weight(0.8f),
            role = AppAmountRole.Compact,
        )
    }
}

@Composable
internal fun CategoryComparisonGroupedChart(rows: List<CategoryComparisonChartRow>) {
    val chartTokens = LocalChartTokens.current
    val statsTokens = LocalStatsTokens.current
    val comparisonTokens = statsTokens.chart.comparison
    val currencyDisplay = LocalCurrencyDisplay.current
    val thisMonthLabel = stringResource(R.string.stats_reports_legend_current_month)
    val lastMonthLabel = stringResource(R.string.stats_reports_legend_previous_month)
    val yearOverYearLabel = stringResource(R.string.stats_reports_legend_year_over_year_month)
    val series = comparisonBarSeries(rows = rows)
    val maxAmount = comparisonMaxAmount(rows = rows, series = series)
    val comparisonA11yBody = remember(rows, thisMonthLabel, lastMonthLabel, yearOverYearLabel, currencyDisplay) {
        comparisonChartA11yBody(
            rows = rows,
            currentMonthLabel = thisMonthLabel,
            previousMonthLabel = lastMonthLabel,
            yearOverYearLabel = yearOverYearLabel,
            currencyDisplay = currencyDisplay,
        )
    }
    val comparisonA11y = stringResource(R.string.stats_reports_comparison_a11y, comparisonA11yBody)

    Column(
        modifier = Modifier.fillMaxWidth().semantics { contentDescription = comparisonA11y },
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Canvas(modifier = Modifier.fillMaxWidth().height(comparisonTokens.height)) {
            drawComparisonBars(
                rows = rows,
                maxAmount = maxAmount,
                series = series,
                guideColor = chartTokens.grid.copy(alpha = comparisonTokens.guideAlpha),
                tokens = comparisonTokens,
            )
        }
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            rows.forEach { row ->
                Text(
                    text = row.category,
                    modifier = Modifier.weight(1f),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelSmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
private fun comparisonBarSeries(rows: List<CategoryComparisonChartRow>): List<ComparisonBarSeries> {
    val chartTokens = LocalChartTokens.current
    return buildList {
        add(
            ComparisonBarSeries(
                color = chartTokens.series.firstOrNull() ?: MaterialTheme.colorScheme.primary,
                amountCents = { it.currentAmountCents },
            ),
        )
        if (rows.any { it.hasPrevious }) {
            add(
                ComparisonBarSeries(
                    color = chartTokens.series.getOrElse(1) { MaterialTheme.colorScheme.secondary },
                    amountCents = { it.previousAmountCents },
                ),
            )
        }
        if (rows.any { it.hasYearOverYear }) {
            add(
                ComparisonBarSeries(
                    color = chartTokens.series.getOrElse(2) { MaterialTheme.colorScheme.tertiary },
                    amountCents = { it.yearOverYearAmountCents },
                ),
            )
        }
    }
}

private fun comparisonMaxAmount(
    rows: List<CategoryComparisonChartRow>,
    series: List<ComparisonBarSeries>,
): Long = max(
    rows.maxOfOrNull { row -> series.maxOf { it.amountCents(row) } } ?: 0L,
    1L,
)

private data class ComparisonBarSeries(
    val color: Color,
    val amountCents: (CategoryComparisonChartRow) -> Long,
)

private fun DrawScope.drawComparisonBars(
    rows: List<CategoryComparisonChartRow>,
    maxAmount: Long,
    series: List<ComparisonBarSeries>,
    guideColor: Color,
    tokens: StatsComparisonChartTokens,
) {
    val top = tokens.verticalPadding.toPx()
    val bottom = size.height - tokens.verticalPadding.toPx()
    val plotHeight = bottom - top
    val groupWidth = size.width / rows.size.coerceAtLeast(1)
    val innerGap = tokens.innerGap.toPx()
    val seriesCount = series.size.coerceAtLeast(1)
    val barWidth = ((groupWidth * tokens.groupWidthFraction - innerGap * (seriesCount - 1)) / seriesCount)
        .coerceIn(tokens.minBarWidth.toPx(), tokens.maxBarWidth.toPx())
    tokens.guideRatios.forEach { ratio ->
        val y = bottom - plotHeight * ratio
        drawLine(
            color = guideColor,
            start = Offset(0f, y),
            end = Offset(size.width, y),
            strokeWidth = tokens.guideStrokeWidth.toPx(),
        )
    }
    rows.forEachIndexed { index, row ->
        val totalBarWidth = barWidth * seriesCount + innerGap * (seriesCount - 1)
        val startX = groupWidth * index + (groupWidth - totalBarWidth) / 2f
        series.forEachIndexed { seriesIndex, chartSeries ->
            val amount = chartSeries.amountCents(row)
            if (amount <= 0L) return@forEachIndexed
            val barHeight = (plotHeight * amount.toFloat() / maxAmount.toFloat())
                .coerceAtLeast(tokens.minBarHeight.toPx())
            val x = startX + seriesIndex * (barWidth + innerGap)
            drawRoundRect(
                color = chartSeries.color.copy(alpha = tokens.barAlpha),
                topLeft = Offset(x, bottom - barHeight),
                size = Size(barWidth, barHeight),
                cornerRadius = CornerRadius(barWidth / 2f, barWidth / 2f),
            )
        }
    }
}

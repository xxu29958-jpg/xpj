package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.DailySpend
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalStatsTokens
import com.ticketbox.ui.design.tabularNum
import kotlin.math.abs

private object ReportsRecentWindowLayout {
    const val DominantPeakPercent = 50
    const val RecentWindowDays = 7
    const val SparseActiveDayLimit = 2
}

@Composable
internal fun ReportsRecentWindowSummary(
    recentTrend: List<DailySpend>,
    modifier: Modifier = Modifier,
) {
    val summary = remember(recentTrend) { summarizeReportsRecentWindow(recentTrend) } ?: return
    val chartPoints = remember(recentTrend) {
        recentTrend
            .takeLast(ReportsRecentWindowLayout.RecentWindowDays)
            .map { day ->
                StatsSpendChartPoint(label = day.label.ifBlank { day.date }, amountCents = day.amountCents)
            }
    }
    val currencyDisplay = LocalCurrencyDisplay.current
    val chartA11y = remember(chartPoints, currencyDisplay) {
        chartPoints.joinToString(separator = "\uFF0C") {
            "${it.label} ${formatDisplayAmount(it.amountCents, currencyDisplay)}"
        }
    }
    ReportsRecentWindowSummaryRow(
        summary = summary,
        insight = reportsRecentWindowInsight(summary),
        chartPoints = chartPoints,
        chartA11y = chartA11y,
        modifier = modifier,
    )
}

@Composable
private fun reportsRecentWindowInsight(summary: ReportsRecentWindowSummaryData): String {
    val currencyDisplay = LocalCurrencyDisplay.current
    val diff = summary.recentThreeAmountCents - summary.previousThreeAmountCents
    return when {
        summary.peakSharePercent >= ReportsRecentWindowLayout.DominantPeakPercent -> stringResource(
            R.string.stats_reports_recent_window_peak_share,
            summary.peakLabel,
            summary.peakSharePercent,
            formatDisplayAmount(summary.otherAverageAmountCents, currencyDisplay),
        )
        summary.previousThreeAmountCents == 0L && summary.recentThreeAmountCents > 0L ->
            stringResource(R.string.stats_recent_trend_vs_previous_new)
        diff > 0L -> stringResource(R.string.stats_recent_trend_vs_previous_up, formatDisplayAmount(abs(diff), currencyDisplay))
        diff < 0L -> stringResource(R.string.stats_recent_trend_vs_previous_down, formatDisplayAmount(abs(diff), currencyDisplay))
        else -> stringResource(R.string.stats_recent_trend_vs_previous_flat)
    }
}

@Composable
private fun ReportsRecentWindowSummaryRow(
    summary: ReportsRecentWindowSummaryData,
    insight: String,
    chartPoints: List<StatsSpendChartPoint>,
    chartA11y: String,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            verticalAlignment = Alignment.Top,
        ) {
            ReportsRecentWindowLabelColumn(modifier = Modifier.weight(1f))
            ReportsRecentWindowValueColumn(
                summary = summary,
                insight = insight,
                modifier = Modifier.weight(1.4f),
            )
        }
        ReportsRecentWindowMovementBody(summary = summary, points = chartPoints, chartA11y = chartA11y)
        ReportsRecentWindowComparisonRows(summary = summary)
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        ) {
            ReportsRecentWindowFact(
                label = stringResource(R.string.stats_reports_recent_window_active_days),
                value = stringResource(R.string.stats_reports_recent_window_active_days_value, summary.activeDayCount),
                modifier = Modifier.weight(1f),
            )
            ReportsRecentWindowFact(
                label = stringResource(R.string.stats_reports_recent_window_peak, summary.peakLabel),
                value = formatDisplayAmount(summary.peakAmountCents, LocalCurrencyDisplay.current),
                modifier = Modifier.weight(1f),
            )
        }
    }
}

@Composable
private fun ReportsRecentWindowMovementBody(
    summary: ReportsRecentWindowSummaryData,
    points: List<StatsSpendChartPoint>,
    chartA11y: String,
) {
    if (summary.shouldUseSparseRows) {
        ReportsRecentWindowSparseRows(
            points = points,
            activeDayCount = summary.activeDayCount,
            chartA11y = chartA11y,
        )
    } else {
        ReportsRecentWindowDayChart(points = points, chartA11y = chartA11y)
    }
}

@Composable
private fun ReportsRecentWindowSparseRows(
    points: List<StatsSpendChartPoint>,
    activeDayCount: Int,
    chartA11y: String,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(
            text = stringResource(R.string.stats_reports_recent_window_sparse, activeDayCount),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        StatsSpendDistributionRows(
            points = points.filter { it.amountCents > 0L },
            spec = StatsSpendDistributionSpec(
                maxRows = ReportsRecentWindowLayout.SparseActiveDayLimit,
                sortByAmount = false,
                includeZeros = false,
                contentDescription = chartA11y,
            ),
        )
    }
}

@Composable
private fun ReportsRecentWindowDayChart(
    points: List<StatsSpendChartPoint>,
    chartA11y: String,
) {
    StatsSpendTrendChart(
        points = points,
        contentDescription = chartA11y,
        height = LocalStatsTokens.current.chart.recentHeight,
        showAllLabels = true,
    )
}

@Composable
private fun ReportsRecentWindowComparisonRows(summary: ReportsRecentWindowSummaryData) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val previousLabel = stringResource(R.string.stats_reports_recent_window_previous_three)
    val recentLabel = stringResource(R.string.stats_reports_recent_window_recent_three)
    val comparisonA11y = stringResource(
        R.string.stats_reports_recent_window_comparison_a11y,
        formatDisplayAmount(summary.previousThreeAmountCents, currencyDisplay),
        formatDisplayAmount(summary.recentThreeAmountCents, currencyDisplay),
    )
    val points = remember(summary, previousLabel, recentLabel) {
        listOf(
            StatsSpendChartPoint(label = previousLabel, amountCents = summary.previousThreeAmountCents),
            StatsSpendChartPoint(label = recentLabel, amountCents = summary.recentThreeAmountCents),
        )
    }
    StatsSpendDistributionRows(
        points = points,
        spec = StatsSpendDistributionSpec(
            maxRows = 2,
            sortByAmount = false,
            includeZeros = true,
            contentDescription = comparisonA11y,
        ),
    )
}

@Composable
private fun ReportsRecentWindowLabelColumn(modifier: Modifier = Modifier) {
    Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Text(
            text = stringResource(R.string.stats_reports_recent_window_title),
            style = MaterialTheme.typography.labelLarge,
            fontWeight = AppTextHierarchy.body.weight,
            maxLines = 1,
        )
        Text(
            text = stringResource(R.string.stats_reports_recent_window_source),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
        )
    }
}

@Composable
private fun ReportsRecentWindowValueColumn(
    summary: ReportsRecentWindowSummaryData,
    insight: String,
    modifier: Modifier = Modifier,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    Column(
        modifier = modifier,
        horizontalAlignment = Alignment.End,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = formatDisplayAmount(summary.totalAmountCents, currencyDisplay),
            style = MaterialTheme.typography.titleSmall.tabularNum(),
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
        )
        Text(
            text = insight,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            textAlign = TextAlign.End,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun ReportsRecentWindowFact(
    label: String,
    value: String,
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

internal data class ReportsRecentWindowSummaryData(
    val totalAmountCents: Long,
    val peakLabel: String,
    val peakAmountCents: Long,
    val peakSharePercent: Int,
    val activeDayCount: Int,
    val otherAverageAmountCents: Long,
    val recentThreeAmountCents: Long,
    val previousThreeAmountCents: Long,
) {
    val shouldUseSparseRows: Boolean =
        activeDayCount in 1..ReportsRecentWindowLayout.SparseActiveDayLimit
}

internal fun summarizeReportsRecentWindow(trend: List<DailySpend>): ReportsRecentWindowSummaryData? {
    val normalized = trend
        .takeLast(ReportsRecentWindowLayout.RecentWindowDays)
        .map { it.copy(amountCents = it.amountCents.coerceAtLeast(0L)) }
    val total = normalized.sumOf { it.amountCents }
    if (total <= 0L) return null
    val peakIndex = normalized.indices.maxByOrNull { normalized[it].amountCents } ?: return null
    val peak = normalized[peakIndex]
    val otherPositiveDays = normalized.filterIndexed { index, day ->
        index != peakIndex && day.amountCents > 0L
    }
    val otherTotal = otherPositiveDays.sumOf { it.amountCents }
    return ReportsRecentWindowSummaryData(
        totalAmountCents = total,
        peakLabel = peak.label,
        peakAmountCents = peak.amountCents,
        peakSharePercent = ((peak.amountCents * 100L) / total).toInt(),
        activeDayCount = normalized.count { it.amountCents > 0L },
        otherAverageAmountCents = if (otherPositiveDays.isNotEmpty()) otherTotal / otherPositiveDays.size else 0L,
        recentThreeAmountCents = normalized.takeLast(3).sumOf { it.amountCents },
        previousThreeAmountCents = normalized.dropLast(3).takeLast(3).sumOf { it.amountCents },
    )
}

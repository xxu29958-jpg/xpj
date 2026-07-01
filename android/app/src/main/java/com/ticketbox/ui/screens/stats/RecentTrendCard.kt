package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.DailySpend
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalStatsTokens
import com.ticketbox.ui.design.tabularNum
import kotlin.math.abs

private const val RecentTrendDominantPeakPercent = 75

@Composable
internal fun RecentTrendCard(trend: List<DailySpend>) {
    val summary = remember(trend) { recentTrendSummary(trend) }
    val currencyDisplay = LocalCurrencyDisplay.current
    val chartA11y = remember(trend, currencyDisplay) {
        trend.joinToString(separator = "\uFF0C") { "${it.label} ${formatDisplayAmount(it.amountCents, currencyDisplay)}" }
    }
    val chartPoints = remember(trend) {
        trend.map { day -> StatsSpendChartPoint(label = day.label, amountCents = day.amountCents) }
    }

    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(stringResource(R.string.stats_recent_trend_title), style = MaterialTheme.typography.titleMedium)
            Text(
                text = stringResource(R.string.stats_recent_trend_source),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        if (trend.isEmpty() || summary.totalAmountCents == 0L) {
            Text(
                text = stringResource(R.string.stats_recent_trend_empty),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        } else {
            RecentTrendComparison(summary)
            RecentTrendDayChart(points = chartPoints, chartA11y = chartA11y)
            RecentTrendMetricStrip(summary)
            if (summary.shouldUseSparseBreakdown) {
                RecentTrendSparseBreakdown(
                    points = chartPoints,
                    positiveDayCount = summary.positiveDayCount,
                    chartA11y = chartA11y,
                )
            }
            if (summary.shouldUseDominanceBreakdown) {
                RecentTrendDominanceBreakdown(summary = summary)
            }
        }
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
    }
}

@Composable
private fun RecentTrendDayChart(
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
internal fun RecentUploadCard(lastUploadAt: String?) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Text(
            stringResource(R.string.stats_recent_upload_title),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = AppTextHierarchy.heading.weight,
        )
        Text(
            text = lastUploadAt?.let { displayTime(it) } ?: stringResource(R.string.stats_recent_upload_empty),
            style = MaterialTheme.typography.titleSmall,
            color = MaterialTheme.colorScheme.onSurface,
            fontWeight = FontWeight.SemiBold,
        )
        Text(
            text = stringResource(R.string.stats_recent_upload_hint),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
    }
}

@Composable
private fun RecentTrendMetricStrip(summary: RecentTrendSummary) {
    val currencyDisplay = LocalCurrencyDisplay.current
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        RecentTrendMetric(
            label = stringResource(R.string.stats_recent_trend_total),
            value = formatDisplayAmount(summary.totalAmountCents, currencyDisplay),
            modifier = Modifier.weight(1f),
        )
        RecentTrendMetric(
            label = summary.peak?.label?.let {
                stringResource(R.string.stats_recent_trend_peak_day, it)
            } ?: stringResource(R.string.stats_recent_trend_peak),
            value = summary.peak?.let { formatDisplayAmount(it.amountCents, currencyDisplay) }.orEmpty(),
            modifier = Modifier.weight(1f),
        )
        RecentTrendMetric(
            label = stringResource(R.string.stats_recent_trend_other_average),
            value = formatDisplayAmount(summary.otherAverageAmountCents, currencyDisplay),
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun RecentTrendMetric(
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

@Composable
private fun RecentTrendComparison(summary: RecentTrendSummary) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val diff = summary.recentThreeAmountCents - summary.previousThreeAmountCents
    val label = when {
        summary.peak != null && summary.peakSharePercent >= 50 -> stringResource(
            R.string.stats_recent_trend_peak_share,
            summary.peak.label,
            summary.peakSharePercent,
        )
        summary.previousThreeAmountCents == 0L && summary.recentThreeAmountCents > 0L ->
            stringResource(R.string.stats_recent_trend_vs_previous_new)
        diff > 0L -> stringResource(
            R.string.stats_recent_trend_vs_previous_up,
            formatDisplayAmount(abs(diff), currencyDisplay),
        )
        diff < 0L -> stringResource(
            R.string.stats_recent_trend_vs_previous_down,
            formatDisplayAmount(abs(diff), currencyDisplay),
        )
        else -> stringResource(R.string.stats_recent_trend_vs_previous_flat)
    }
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.Bottom,
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.primary,
            style = MaterialTheme.typography.titleSmall,
            fontWeight = FontWeight.SemiBold,
            modifier = Modifier.weight(1f),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun RecentTrendDominanceBreakdown(summary: RecentTrendSummary) {
    val currencyDisplay = LocalCurrencyDisplay.current
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        summary.peak?.takeIf { it.amountCents > 0L }?.let { peak ->
            RecentTrendBreakdownRow(
                label = stringResource(R.string.stats_recent_trend_peak_day, peak.label),
                amountCents = peak.amountCents,
                currencyDisplay = currencyDisplay,
            )
        }
        if (summary.otherPositiveDayCount > 0) {
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.subtle))
            RecentTrendBreakdownRow(
                label = stringResource(R.string.stats_recent_trend_other_days, summary.otherPositiveDayCount),
                amountCents = summary.otherTotalAmountCents,
                currencyDisplay = currencyDisplay,
            )
        }
    }
}

@Composable
private fun RecentTrendBreakdownRow(
    label: String,
    amountCents: Long,
    currencyDisplay: CurrencyDisplay,
) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = formatDisplayAmount(amountCents, currencyDisplay),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.bodyMedium.tabularNum(),
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun RecentTrendSparseBreakdown(
    points: List<StatsSpendChartPoint>,
    positiveDayCount: Int,
    chartA11y: String,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(
            text = stringResource(R.string.stats_recent_trend_sparse, positiveDayCount),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        StatsSpendDistributionRows(
            points = points.filter { it.amountCents > 0L },
            spec = StatsSpendDistributionSpec(
                maxRows = 2,
                sortByAmount = false,
                includeZeros = false,
                contentDescription = chartA11y,
            ),
        )
    }
}

private data class RecentTrendSummary(
    val totalAmountCents: Long,
    val peak: DailySpend?,
    val positiveDayCount: Int,
    val peakSharePercent: Int,
    val otherPositiveDayCount: Int,
    val otherTotalAmountCents: Long,
    val otherAverageAmountCents: Long,
    val recentThreeAmountCents: Long,
    val previousThreeAmountCents: Long,
) {
    val shouldUseSparseBreakdown: Boolean =
        positiveDayCount in 1..2
    val shouldUseDominanceBreakdown: Boolean =
        positiveDayCount >= 3 && peakSharePercent >= RecentTrendDominantPeakPercent
}

private fun recentTrendSummary(trend: List<DailySpend>): RecentTrendSummary {
    val normalized = trend.map { it.copy(amountCents = it.amountCents.coerceAtLeast(0L)) }
    val total = normalized.sumOf { it.amountCents }
    val peakIndex = normalized.indices.maxByOrNull { normalized[it].amountCents }
    val peak = peakIndex?.let { normalized[it] }
    val otherPositiveDays = normalized.filterIndexed { index, day ->
        index != peakIndex && day.amountCents > 0L
    }
    val otherTotal = otherPositiveDays.sumOf { it.amountCents }
    return RecentTrendSummary(
        totalAmountCents = total,
        peak = peak,
        positiveDayCount = normalized.count { it.amountCents > 0L },
        peakSharePercent = if (total > 0L) {
            (((peak?.amountCents ?: 0L) * 100) / total).toInt()
        } else {
            0
        },
        otherPositiveDayCount = otherPositiveDays.size,
        otherTotalAmountCents = otherTotal,
        otherAverageAmountCents = if (otherPositiveDays.isNotEmpty()) otherTotal / otherPositiveDays.size else 0L,
        recentThreeAmountCents = normalized.takeLast(3).sumOf { it.amountCents },
        previousThreeAmountCents = normalized.dropLast(3).takeLast(3).sumOf { it.amountCents },
    )
}

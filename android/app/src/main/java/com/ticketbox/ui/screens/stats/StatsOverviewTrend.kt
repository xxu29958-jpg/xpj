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
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.DailySpend
import com.ticketbox.domain.model.ReportTrendPoint
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.tabularNum

private const val HeroTrendDominantPeakPercent = 75

@Composable
internal fun HeroSpendTrend(
    dailyTrend: List<DailySpend>,
    reportTrend: List<ReportTrendPoint>,
    currencyDisplay: CurrencyDisplay,
) {
    val points = remember(reportTrend, dailyTrend) { heroSpendTrendPoints(reportTrend, dailyTrend) }
    val visiblePoints = rememberSpendWindowChartPoints(points = points, maxWindows = 6)
    val summary = remember(points) { heroSpendTrendSummary(points) }
    val chartA11y = remember(points, currencyDisplay) {
        points.joinToString(separator = "\uFF0C") {
            "${it.label} ${formatDisplayAmount(it.amountCents, currencyDisplay)}"
        }
    }

    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        HeroTrendHeader(summary = summary, currencyDisplay = currencyDisplay)
        if (points.isEmpty() || points.all { it.amountCents <= 0L }) {
            HeroTrendEmpty()
        } else {
            HeroTrendBody(
                points = visiblePoints,
                summary = summary,
                currencyDisplay = currencyDisplay,
                chartA11y = chartA11y,
            )
        }
    }
}

@Composable
private fun HeroTrendHeader(
    summary: HeroSpendTrendSummary,
    currencyDisplay: CurrencyDisplay,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
    ) {
        Text(
            text = stringResource(R.string.stats_overview_trend_title),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelMedium,
        )
        heroTrendPeakLabel(summary, currencyDisplay)?.let { peakLabel ->
            Text(
                text = peakLabel,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelSmall.tabularNum(),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun HeroTrendEmpty() {
    Text(
        text = stringResource(R.string.stats_overview_trend_empty),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodySmall,
    )
}

@Composable
private fun HeroTrendBody(
    points: List<StatsSpendChartPoint>,
    summary: HeroSpendTrendSummary,
    currencyDisplay: CurrencyDisplay,
    chartA11y: String,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
    ) {
        HeroTrendFact(
            label = stringResource(R.string.stats_reports_chart_active_days),
            value = stringResource(R.string.stats_reports_chart_active_days_value, summary.positivePointCount),
            modifier = Modifier.weight(1f),
        )
        HeroTrendFact(
            label = stringResource(R.string.stats_overview_trend_peak_share_label),
            value = stringResource(R.string.stats_overview_trend_peak_share_value, summary.peakSharePercent),
            modifier = Modifier.weight(1f),
        )
        HeroTrendFact(
            label = stringResource(R.string.stats_overview_trend_other_average_label),
            value = formatDisplayAmount(summary.otherAverageAmountCents, currencyDisplay),
            modifier = Modifier.weight(1f),
        )
    }
    if (summary.shouldUseDominanceBreakdown) {
        HeroTrendDominanceBreakdown(summary = summary, currencyDisplay = currencyDisplay)
    } else {
        StatsSpendDistributionRows(
            points = points,
            spec = StatsSpendDistributionSpec(
                maxRows = 6,
                sortByAmount = false,
                includeZeros = false,
                contentDescription = chartA11y,
            ),
        )
    }
}

@Composable
private fun HeroTrendFact(
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
private fun HeroTrendDominanceBreakdown(
    summary: HeroSpendTrendSummary,
    currencyDisplay: CurrencyDisplay,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        summary.peak?.takeIf { it.amountCents > 0L }?.let { peak ->
            HeroTrendBreakdownRow(
                label = stringResource(R.string.stats_overview_trend_peak, peak.label),
                amountCents = peak.amountCents,
                currencyDisplay = currencyDisplay,
            )
        }
        if (summary.otherPositivePointCount > 0) {
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.subtle))
            HeroTrendBreakdownRow(
                label = stringResource(R.string.stats_recent_trend_other_days, summary.otherPositivePointCount),
                amountCents = summary.otherTotalAmountCents,
                currencyDisplay = currencyDisplay,
            )
        }
    }
}

@Composable
private fun HeroTrendBreakdownRow(
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

private data class HeroSpendTrendSummary(
    val peak: StatsSpendChartPoint?,
    val positivePointCount: Int,
    val peakSharePercent: Int,
    val otherPositivePointCount: Int,
    val otherTotalAmountCents: Long,
    val otherAverageAmountCents: Long,
) {
    val shouldUseDominanceBreakdown: Boolean =
        positivePointCount >= 3 && peakSharePercent >= HeroTrendDominantPeakPercent
}

private fun heroSpendTrendSummary(points: List<StatsSpendChartPoint>): HeroSpendTrendSummary {
    val normalized = points.map { it.copy(amountCents = it.amountCents.coerceAtLeast(0L)) }
    val total = normalized.sumOf { it.amountCents }
    val peakIndex = normalized.indices.maxByOrNull { normalized[it].amountCents }
    val peak = peakIndex?.let { normalized[it] }
    val otherPositivePoints = normalized.filterIndexed { index, point ->
        index != peakIndex && point.amountCents > 0L
    }
    val otherTotal = otherPositivePoints.sumOf { it.amountCents }
    return HeroSpendTrendSummary(
        peak = peak,
        positivePointCount = normalized.count { it.amountCents > 0L },
        peakSharePercent = if (total > 0L) (((peak?.amountCents ?: 0L) * 100L) / total).toInt() else 0,
        otherPositivePointCount = otherPositivePoints.size,
        otherTotalAmountCents = otherTotal,
        otherAverageAmountCents = if (otherPositivePoints.isNotEmpty()) otherTotal / otherPositivePoints.size else 0L,
    )
}

@Composable
private fun heroTrendPeakLabel(
    summary: HeroSpendTrendSummary,
    currencyDisplay: CurrencyDisplay,
): String? {
    val peak = summary.peak?.takeIf { it.amountCents > 0L }
    return peak?.let {
        stringResource(
            R.string.stats_overview_trend_peak_amount,
            it.label,
            formatDisplayAmount(it.amountCents, currencyDisplay),
        )
    }
}

private fun heroSpendTrendPoints(
    reportTrend: List<ReportTrendPoint>,
    dailyTrend: List<DailySpend>,
): List<StatsSpendChartPoint> {
    val serverPoints = reportTrend
        .filter { it.label.isNotBlank() || it.bucket.isNotBlank() }
        .map {
            StatsSpendChartPoint(
                label = it.label.ifBlank { it.bucket },
                amountCents = it.amountCents.coerceAtLeast(0L),
            )
        }
    if (serverPoints.isNotEmpty()) {
        return serverPoints
    }
    return dailyTrend.map {
        StatsSpendChartPoint(label = it.label.ifBlank { it.date }, amountCents = it.amountCents.coerceAtLeast(0L))
    }
}

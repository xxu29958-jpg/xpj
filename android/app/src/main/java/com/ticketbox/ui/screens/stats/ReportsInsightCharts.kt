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
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.AppAdaptiveMetricGrid
import com.ticketbox.ui.components.AppEndAlignedAmountText
import com.ticketbox.presentation.formatDisplayAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalChartTokens
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalStatsTokens
import com.ticketbox.ui.design.tabularNum

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
internal fun ReportsTrendDetails(summary: ReportsTrendEvidence) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        ReportsTrendChartSummary(summary)
        ReportsTrendFactStrip(summary)
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
    AppAdaptiveMetricGrid(itemCount = 3) { index, metricModifier ->
        if (index == 0) ReportsTrendFact(
            label = stringResource(R.string.stats_reports_chart_active_days),
            value = stringResource(R.string.stats_reports_chart_active_days_value, summary.positiveBucketCount),
            modifier = metricModifier,
        )
        else if (index == 1) ReportsTrendFact(
            label = stringResource(R.string.stats_reports_chart_peak_share_label),
            value = stringResource(R.string.stats_reports_chart_peak_share_value, summary.peakSharePercent),
            modifier = metricModifier,
        )
        else ReportsTrendFact(
            label = stringResource(R.string.stats_reports_chart_other_average_label),
            value = formatDisplayAmount(summary.otherAverageAmountCents, LocalCurrencyDisplay.current),
            isAmount = true,
            modifier = metricModifier,
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

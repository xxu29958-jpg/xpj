package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalChartTokens
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalStatsTokens
import com.ticketbox.ui.design.tabularNum
import kotlin.math.ceil

internal data class StatsSpendChartPoint(
    val label: String,
    val amountCents: Long,
)

internal data class StatsSpendDistributionSpec(
    val maxRows: Int,
    val sortByAmount: Boolean,
    val includeZeros: Boolean,
    val contentDescription: String,
)

private data class StatsSpendDistributionRow(
    val label: String,
    val amountCents: Long,
)

internal data class StatsSpendWindowPoint(
    val startLabel: String,
    val endLabel: String,
    val amountCents: Long,
)

internal fun activeSpendChartWindow(points: List<StatsSpendChartPoint>): List<StatsSpendChartPoint> {
    val firstPositive = points.indexOfFirst { it.amountCents > 0L }
    if (firstPositive < 0) return points
    val lastPositive = points.indexOfLast { it.amountCents > 0L }
    return points.subList(firstPositive, lastPositive + 1)
}

internal fun spendTrendWindows(
    points: List<StatsSpendChartPoint>,
    maxWindows: Int,
): List<StatsSpendWindowPoint> {
    val active = activeSpendChartWindow(points)
    if (active.size <= maxWindows.coerceAtLeast(1)) {
        return active.map { point ->
            StatsSpendWindowPoint(
                startLabel = point.label,
                endLabel = point.label,
                amountCents = point.amountCents.coerceAtLeast(0L),
            )
        }
    }
    val bucketSize = ceil(active.size.toDouble() / maxWindows.coerceAtLeast(1).toDouble()).toInt().coerceAtLeast(1)
    return active
        .chunked(bucketSize)
        .map { bucket ->
            StatsSpendWindowPoint(
                startLabel = bucket.first().label,
                endLabel = bucket.last().label,
                amountCents = bucket.sumOf { it.amountCents.coerceAtLeast(0L) },
            )
        }
}

@Composable
internal fun rememberSpendWindowChartPoints(
    points: List<StatsSpendChartPoint>,
    maxWindows: Int,
): List<StatsSpendChartPoint> {
    val windows = remember(points, maxWindows) { spendTrendWindows(points, maxWindows) }
    return windows.map { window ->
        StatsSpendChartPoint(
            label = if (window.startLabel == window.endLabel) {
                window.startLabel
            } else {
                stringResource(R.string.stats_chart_window_label, window.startLabel, window.endLabel)
            },
            amountCents = window.amountCents,
        )
    }
}

@Composable
internal fun StatsSpendDistributionRows(
    points: List<StatsSpendChartPoint>,
    spec: StatsSpendDistributionSpec,
    modifier: Modifier = Modifier,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val rows = remember(points, spec) {
        val normalized = points
            .map { StatsSpendDistributionRow(label = it.label, amountCents = it.amountCents.coerceAtLeast(0L)) }
            .filter { spec.includeZeros || it.amountCents > 0L }
        val ordered = if (spec.sortByAmount) {
            normalized.sortedByDescending { it.amountCents }
        } else {
            normalized
        }
        val visible = ordered.take(spec.maxRows)
        val remainder = ordered.drop(spec.maxRows)
        if (remainder.isNotEmpty()) {
            visible + StatsSpendDistributionRow(
                label = "",
                amountCents = remainder.sumOf { it.amountCents },
            )
        } else {
            visible
        }
    }
    if (rows.isEmpty()) {
        return
    }
    val maxAmount = remember(rows) { rows.maxOfOrNull { it.amountCents }?.coerceAtLeast(1L) ?: 1L }
    val remainderCount = remember(points, spec) {
        points.count { spec.includeZeros || it.amountCents > 0L }.minus(spec.maxRows).coerceAtLeast(0)
    }
    val lastIndex = rows.lastIndex
    Column(
        modifier = modifier.semantics { this.contentDescription = spec.contentDescription },
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        rows.forEachIndexed { index, row ->
            val label = if (index == lastIndex && remainderCount > 0) {
                stringResource(R.string.stats_chart_distribution_remaining, remainderCount)
            } else {
                row.label
            }
            StatsSpendDistributionRowView(
                label = label,
                amountCents = row.amountCents,
                maxAmountCents = maxAmount,
                highlighted = row.amountCents == maxAmount && row.amountCents > 0L,
            )
        }
    }
}

@Composable
private fun StatsSpendDistributionRowView(
    label: String,
    amountCents: Long,
    maxAmountCents: Long,
    highlighted: Boolean,
) {
    val chartTokens = LocalChartTokens.current
    val statsTokens = LocalStatsTokens.current
    val distributionTokens = statsTokens.chart.distribution
    val currencyDisplay = LocalCurrencyDisplay.current
    val ratio = (amountCents.toFloat() / maxAmountCents.toFloat()).coerceIn(0f, 1f)
    val fillFraction = if (amountCents > 0L) {
        ratio.coerceAtLeast(distributionTokens.minFillFraction)
    } else {
        0f
    }
    val fillColor = (chartTokens.series.firstOrNull() ?: MaterialTheme.colorScheme.primary).copy(
        alpha = if (highlighted) statsTokens.chart.emphasisAlpha else statsTokens.chart.quietAlpha,
    )
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            modifier = Modifier.weight(distributionTokens.labelWeight),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        StatsSpendDistributionValueBar(
            fillFraction = fillFraction,
            fillColor = fillColor,
            modifier = Modifier.weight(distributionTokens.trackWeight),
        )
        Text(
            text = formatDisplayAmount(amountCents, currencyDisplay),
            modifier = Modifier.weight(distributionTokens.amountWeight),
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.labelMedium.tabularNum(),
            fontWeight = if (highlighted) AppTextHierarchy.heading.weight else FontWeight.Normal,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            textAlign = TextAlign.End,
        )
    }
}

@Composable
private fun StatsSpendDistributionValueBar(
    fillFraction: Float,
    fillColor: Color,
    modifier: Modifier = Modifier,
) {
    val chartTokens = LocalChartTokens.current
    val statsTokens = LocalStatsTokens.current
    Box(
        modifier = modifier.height(statsTokens.chart.distributionHeight),
        contentAlignment = Alignment.CenterStart,
    ) {
        if (fillFraction > 0f) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(fillFraction)
                    .height(statsTokens.chart.distributionHeight)
                    .clip(RoundedCornerShape(AppRadius.pill))
                    .background(fillColor),
            )
        } else {
            Box(
                modifier = Modifier
                    .width(AppSpacing.contentGap)
                    .height(statsTokens.chart.distributionHeight)
                    .clip(RoundedCornerShape(AppRadius.pill))
                    .background(chartTokens.empty.copy(alpha = statsTokens.chart.guideAlpha)),
            )
        }
    }
}

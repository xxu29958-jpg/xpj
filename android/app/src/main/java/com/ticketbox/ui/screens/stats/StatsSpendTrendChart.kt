package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.selection.selectable
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalChartTokens
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalStatsTokens

private object SpendTrendChartLayout {
    val TopInset = 4.dp
    val BottomInset = 5.dp
    val HorizontalInset = 4.dp
    val MinimumBarWidth = 6.dp
    val MaximumBarWidth = 22.dp
    val MinimumBarHeight = 8.dp
    val ZeroPointSize = 4.dp
    val GuideStrokeWidth = 1.dp
    const val BarWidthFraction = 0.56f
    const val MiddleGuideRatio = 0.5f
}

@Composable
internal fun AdaptiveStatsSpendTrendChart(
    points: List<StatsSpendChartPoint>,
    contentDescription: String,
    modifier: Modifier = Modifier,
    height: Dp? = null,
    maxWindows: Int = 7,
) {
    val minimumLabelWidth = LocalStatsTokens.current.chart.minimumRangeLabelWidth
    BoxWithConstraints(modifier = modifier.fillMaxWidth()) {
        val windowCount = remember(maxWidth, maxWindows, minimumLabelWidth) {
            trendWindowCountForAvailableWidth(
                availableWidthDp = maxWidth.value,
                minimumLabelWidthDp = minimumLabelWidth.value,
                maxWindows = maxWindows,
            )
        }
        val visiblePoints = rememberSpendWindowChartPoints(
            points = points,
            maxWindows = windowCount,
        )
        StatsSpendTrendChart(
            points = visiblePoints,
            contentDescription = contentDescription,
            modifier = Modifier.fillMaxWidth(),
            height = height,
        )
    }
}

@Composable
internal fun StatsSpendTrendChart(
    points: List<StatsSpendChartPoint>,
    contentDescription: String,
    modifier: Modifier = Modifier,
    height: Dp? = null,
) {
    val normalizedPoints = remember(points) {
        points.map { it.copy(amountCents = it.amountCents.coerceAtLeast(0L)) }
    }
    if (normalizedPoints.isEmpty()) return

    val statsTokens = LocalStatsTokens.current
    val currencyDisplay = LocalCurrencyDisplay.current
    val maxAmount = remember(normalizedPoints) {
        normalizedPoints.maxOfOrNull { it.amountCents }?.coerceAtLeast(1L) ?: 1L
    }
    val chartStyle = spendTrendChartStyle()
    var selectedIndex by remember(normalizedPoints) {
        mutableIntStateOf(defaultTrendPointIndex(normalizedPoints))
    }
    var userSelected by remember(normalizedPoints) { mutableStateOf(false) }
    val selectedPoint = normalizedPoints[selectedIndex]
    val selectedReadout = stringResource(
        if (userSelected) R.string.stats_chart_selected_readout else R.string.stats_chart_peak_readout,
        selectedPoint.label.replace('\n', ' '),
        formatDisplayAmount(selectedPoint.amountCents, currencyDisplay),
    )
    val selectPoint: (Int) -> Unit = { index ->
        selectedIndex = index.coerceIn(normalizedPoints.indices)
        userSelected = true
    }

    Column(
        modifier = modifier
            .fillMaxWidth()
            .semantics {
                this.contentDescription = contentDescription
                stateDescription = selectedReadout
            },
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        TrendPointReadout(text = selectedReadout)
        Canvas(
            modifier = Modifier
                .fillMaxWidth()
                .height(height ?: statsTokens.chart.monthlyHeight)
                .pointerInput(normalizedPoints) {
                    detectTapGestures { offset ->
                        selectPoint(trendPointIndexForTap(offset.x, size.width.toFloat(), normalizedPoints.size))
                    }
                },
        ) {
            drawSpendTrendBars(
                points = normalizedPoints,
                maxAmount = maxAmount,
                selectedIndex = selectedIndex,
                style = chartStyle,
            )
        }
        TrendPointLabels(
            points = normalizedPoints,
            selectedIndex = selectedIndex,
            currencyDisplay = currencyDisplay,
            onSelect = selectPoint,
        )
    }
}

@Composable
private fun TrendPointReadout(text: String) {
    Text(
        text = text,
        modifier = Modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.primary,
        style = MaterialTheme.typography.labelMedium,
        fontWeight = FontWeight.SemiBold,
        textAlign = TextAlign.End,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
    )
}

@Composable
private fun TrendPointLabels(
    points: List<StatsSpendChartPoint>,
    selectedIndex: Int,
    currencyDisplay: CurrencyDisplay,
    onSelect: (Int) -> Unit,
) {
    Row(modifier = Modifier.fillMaxWidth()) {
        points.forEachIndexed { index, point ->
            val amount = formatDisplayAmount(point.amountCents, currencyDisplay)
            val pointDescription = stringResource(
                R.string.stats_chart_point_a11y,
                point.label.replace('\n', ' '),
                amount,
            )
            Box(
                modifier = Modifier
                    .weight(1f)
                    .heightIn(min = AppSpacing.controlMinHeight)
                    .selectable(
                        selected = index == selectedIndex,
                        role = Role.RadioButton,
                        onClick = { onSelect(index) },
                    )
                    .semantics {
                        contentDescription = pointDescription
                    },
                contentAlignment = Alignment.TopCenter,
            ) {
                Text(
                    text = point.label,
                    color = if (index == selectedIndex) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                    style = MaterialTheme.typography.labelSmall,
                    fontWeight = if (index == selectedIndex) FontWeight.SemiBold else FontWeight.Normal,
                    textAlign = TextAlign.Center,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

private data class SpendTrendChartStyle(
    val primary: Color,
    val grid: Color,
    val gridEmphasis: Color,
    val emphasisAlpha: Float,
    val quietAlpha: Float,
)

private data class SpendTrendPlot(
    val bottom: Float,
    val height: Float,
    val horizontalInset: Float,
)

private fun DrawScope.drawSpendTrendBars(
    points: List<StatsSpendChartPoint>,
    maxAmount: Long,
    selectedIndex: Int,
    style: SpendTrendChartStyle,
) {
    val top = SpendTrendChartLayout.TopInset.toPx()
    val bottom = size.height - SpendTrendChartLayout.BottomInset.toPx()
    val plotHeight = (bottom - top).coerceAtLeast(1f)
    val horizontalInset = SpendTrendChartLayout.HorizontalInset.toPx()
    val plot = SpendTrendPlot(bottom = bottom, height = plotHeight, horizontalInset = horizontalInset)
    val bucketWidth = (size.width - horizontalInset * 2f) / points.size.coerceAtLeast(1)
    val barWidth = (bucketWidth * SpendTrendChartLayout.BarWidthFraction).coerceIn(
        SpendTrendChartLayout.MinimumBarWidth.toPx(),
        SpendTrendChartLayout.MaximumBarWidth.toPx(),
    )
    val maxPointAmount = points.maxOfOrNull { it.amountCents } ?: 0L
    val zeroDotSize = SpendTrendChartLayout.ZeroPointSize.toPx()
    val positivePoints = points.filter { it.amountCents > 0L }
    val averageAmount = if (positivePoints.size > 1) {
        positivePoints.sumOf { it.amountCents } / positivePoints.size
    } else {
        0L
    }

    drawSpendTrendGuides(plot = plot, maxAmount = maxAmount, averageAmount = averageAmount, style = style)

    points.forEachIndexed { index, point ->
        val x = horizontalInset + bucketWidth * index + (bucketWidth - barWidth) / 2f
        if (point.amountCents <= 0L) {
            drawRoundRect(
                color = if (index == selectedIndex) style.primary else style.grid,
                topLeft = Offset(x + (barWidth - zeroDotSize) / 2f, bottom - zeroDotSize),
                size = Size(zeroDotSize, zeroDotSize),
                cornerRadius = CornerRadius(zeroDotSize / 2f, zeroDotSize / 2f),
            )
            return@forEachIndexed
        }
        val ratio = point.amountCents.toFloat() / maxAmount.toFloat()
        val barHeight = (plotHeight * ratio).coerceAtLeast(SpendTrendChartLayout.MinimumBarHeight.toPx())
        val alpha = if (index == selectedIndex || point.amountCents == maxPointAmount) {
            style.emphasisAlpha
        } else {
            style.quietAlpha
        }
        drawRoundRect(
            color = style.primary.copy(alpha = alpha),
            topLeft = Offset(x, bottom - barHeight),
            size = Size(barWidth, barHeight),
            cornerRadius = CornerRadius(barWidth / 2f, barWidth / 2f),
        )
    }
}

private fun DrawScope.drawSpendTrendGuides(
    plot: SpendTrendPlot,
    maxAmount: Long,
    averageAmount: Long,
    style: SpendTrendChartStyle,
) {
    drawLine(
        color = style.grid,
        start = Offset(0f, plot.bottom - plot.height * SpendTrendChartLayout.MiddleGuideRatio),
        end = Offset(size.width, plot.bottom - plot.height * SpendTrendChartLayout.MiddleGuideRatio),
        strokeWidth = SpendTrendChartLayout.GuideStrokeWidth.toPx(),
    )
    if (averageAmount > 0L && averageAmount < maxAmount) {
        val averageY = plot.bottom - plot.height * averageAmount.toFloat() / maxAmount.toFloat()
        drawLine(
            color = style.gridEmphasis,
            start = Offset(plot.horizontalInset, averageY),
            end = Offset(size.width - plot.horizontalInset, averageY),
            strokeWidth = SpendTrendChartLayout.GuideStrokeWidth.toPx(),
        )
    }
    drawLine(
        color = style.grid,
        start = Offset(0f, plot.bottom),
        end = Offset(size.width, plot.bottom),
        strokeWidth = SpendTrendChartLayout.GuideStrokeWidth.toPx(),
    )
}

@Composable
private fun spendTrendChartStyle(): SpendTrendChartStyle {
    val chartTokens = LocalChartTokens.current
    val statsTokens = LocalStatsTokens.current
    return remember(chartTokens, statsTokens) {
        SpendTrendChartStyle(
            primary = chartTokens.series.firstOrNull() ?: Color(0xff5b6ee1),
            grid = chartTokens.grid,
            gridEmphasis = chartTokens.gridEmphasis,
            emphasisAlpha = statsTokens.chart.emphasisAlpha,
            quietAlpha = statsTokens.chart.quietAlpha,
        )
    }
}

internal fun trendAxisLabels(points: List<StatsSpendChartPoint>): List<String> =
    points.map { it.label }.filter { it.isNotBlank() }

internal fun defaultTrendPointIndex(points: List<StatsSpendChartPoint>): Int =
    points.indices.maxByOrNull { points[it].amountCents } ?: 0

internal fun trendPointIndexForTap(x: Float, width: Float, pointCount: Int): Int {
    if (pointCount <= 1 || width <= 0f) return 0
    return (x / width * pointCount).toInt().coerceIn(0, pointCount - 1)
}

internal fun trendWindowCountForAvailableWidth(
    availableWidthDp: Float,
    minimumLabelWidthDp: Float,
    maxWindows: Int,
): Int {
    val resolvedMax = maxWindows.coerceAtLeast(1)
    return (availableWidthDp / minimumLabelWidthDp.coerceAtLeast(1f))
        .toInt()
        .coerceIn(1, resolvedMax)
}

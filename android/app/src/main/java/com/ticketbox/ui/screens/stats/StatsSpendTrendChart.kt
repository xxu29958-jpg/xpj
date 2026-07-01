package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
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
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalChartTokens
import com.ticketbox.ui.design.LocalStatsTokens

@Composable
internal fun StatsSpendTrendChart(
    points: List<StatsSpendChartPoint>,
    contentDescription: String,
    modifier: Modifier = Modifier,
    height: Dp? = null,
    showAllLabels: Boolean = false,
) {
    val chartTokens = LocalChartTokens.current
    val statsTokens = LocalStatsTokens.current
    val normalizedPoints = remember(points) {
        points.map { it.copy(amountCents = it.amountCents.coerceAtLeast(0L)) }
    }
    val maxAmount = remember(normalizedPoints) {
        normalizedPoints.maxOfOrNull { it.amountCents }?.coerceAtLeast(1L) ?: 1L
    }
    val axisLabels = remember(normalizedPoints, showAllLabels) { trendAxisLabels(normalizedPoints, showAllLabels) }
    val chartStyle = remember(chartTokens, statsTokens) {
        SpendTrendChartStyle(
            primary = chartTokens.series.firstOrNull() ?: Color(0xff5b6ee1),
            grid = chartTokens.grid,
            gridEmphasis = chartTokens.gridEmphasis,
            emphasisAlpha = statsTokens.chart.emphasisAlpha,
            quietAlpha = statsTokens.chart.quietAlpha,
        )
    }
    if (normalizedPoints.isEmpty()) return

    Column(
        modifier = modifier
            .fillMaxWidth()
            .semantics { this.contentDescription = contentDescription },
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Canvas(
            modifier = Modifier
                .fillMaxWidth()
                .height(height ?: statsTokens.chart.monthlyHeight),
        ) {
            drawSpendTrendBars(
                points = normalizedPoints,
                maxAmount = maxAmount,
                style = chartStyle,
            )
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = if (axisLabels.size == 1) {
                Arrangement.Center
            } else {
                Arrangement.SpaceBetween
            },
        ) {
            axisLabels.forEach { label ->
                Text(
                    text = label,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelSmall,
                    maxLines = 1,
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

private fun DrawScope.drawSpendTrendBars(
    points: List<StatsSpendChartPoint>,
    maxAmount: Long,
    style: SpendTrendChartStyle,
) {
    val top = 4.dp.toPx()
    val bottom = size.height - 5.dp.toPx()
    val plotHeight = (bottom - top).coerceAtLeast(1f)
    val horizontalInset = 4.dp.toPx()
    val bucketWidth = (size.width - horizontalInset * 2f) / points.size.coerceAtLeast(1)
    val barWidth = (bucketWidth * 0.56f).coerceIn(6.dp.toPx(), 22.dp.toPx())
    val maxPointAmount = points.maxOfOrNull { it.amountCents } ?: 0L
    val zeroDotSize = 4.dp.toPx()
    val positivePoints = points.filter { it.amountCents > 0L }
    val averageAmount = if (positivePoints.size > 1) {
        positivePoints.sumOf { it.amountCents } / positivePoints.size
    } else {
        0L
    }

    drawLine(
        color = style.grid,
        start = Offset(0f, bottom - plotHeight * 0.5f),
        end = Offset(size.width, bottom - plotHeight * 0.5f),
        strokeWidth = 1.dp.toPx(),
    )
    if (averageAmount > 0L && averageAmount < maxAmount) {
        val averageY = bottom - plotHeight * averageAmount.toFloat() / maxAmount.toFloat()
        drawLine(
            color = style.gridEmphasis,
            start = Offset(horizontalInset, averageY),
            end = Offset(size.width - horizontalInset, averageY),
            strokeWidth = 1.dp.toPx(),
        )
    }

    drawLine(
        color = style.grid,
        start = Offset(0f, bottom),
        end = Offset(size.width, bottom),
        strokeWidth = 1.dp.toPx(),
    )

    points.forEachIndexed { index, point ->
        val x = horizontalInset + bucketWidth * index + (bucketWidth - barWidth) / 2f
        if (point.amountCents <= 0L) {
            drawRoundRect(
                color = style.grid,
                topLeft = Offset(x + (barWidth - zeroDotSize) / 2f, bottom - zeroDotSize),
                size = Size(zeroDotSize, zeroDotSize),
                cornerRadius = CornerRadius(zeroDotSize / 2f, zeroDotSize / 2f),
            )
            return@forEachIndexed
        }
        val ratio = point.amountCents.toFloat() / maxAmount.toFloat()
        val barHeight = (plotHeight * ratio).coerceAtLeast(8.dp.toPx())
        val alpha = if (point.amountCents == maxPointAmount) style.emphasisAlpha else style.quietAlpha
        drawRoundRect(
            color = style.primary.copy(alpha = alpha),
            topLeft = Offset(x, bottom - barHeight),
            size = Size(barWidth, barHeight),
            cornerRadius = CornerRadius(barWidth / 2f, barWidth / 2f),
        )
    }
}

internal fun trendAxisLabels(points: List<StatsSpendChartPoint>, showAllLabels: Boolean = false): List<String> {
    if (points.isEmpty()) return emptyList()
    if (showAllLabels) return points.map { it.label }.filter { it.isNotBlank() }
    if (points.size == 1) return listOf(points.first().label)
    val middle = points.size / 2
    return listOf(0, middle, points.lastIndex)
        .distinct()
        .map { points[it].label }
        .filter { it.isNotBlank() }
}

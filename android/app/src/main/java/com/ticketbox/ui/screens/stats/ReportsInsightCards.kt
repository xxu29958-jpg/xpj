package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.patrykandpatrick.vico.compose.cartesian.CartesianChartHost
import com.patrykandpatrick.vico.compose.cartesian.axis.HorizontalAxis
import com.patrykandpatrick.vico.compose.cartesian.axis.VerticalAxis
import com.patrykandpatrick.vico.compose.cartesian.data.CartesianChartModelProducer
import com.patrykandpatrick.vico.compose.cartesian.data.CartesianValueFormatter
import com.patrykandpatrick.vico.compose.cartesian.data.lineSeries
import com.patrykandpatrick.vico.compose.cartesian.layer.LineCartesianLayer
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLine
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberLineCartesianLayer
import com.patrykandpatrick.vico.compose.cartesian.rememberCartesianChart
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoScrollState
import com.patrykandpatrick.vico.compose.common.Fill
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.ReportCategoryComparison
import com.ticketbox.domain.model.ReportMerchantRanking
import com.ticketbox.domain.model.ReportTrendPoint
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalChartTokens
import com.ticketbox.ui.design.LocalCurrencyDisplay
import java.math.BigDecimal
import java.math.RoundingMode
import kotlin.math.abs

@Composable
internal fun ReportsInsightCard(
    overview: ReportsOverview,
    modifier: Modifier = Modifier,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val chartPoints = remember(overview.trend) { reportTrendChartPoints(overview.trend) }

    AppGlassCard(modifier = modifier, containerAlpha = 0.96f) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(2.dp),
                ) {
                    Text("动态图表", style = MaterialTheme.typography.titleMedium, fontWeight = AppTextHierarchy.heading.weight)
                    Text(
                        text = "${overview.month} · 服务端聚合 · ${overview.count} 笔",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                Text(
                    text = formatDisplayAmount(overview.totalAmountCents, currencyDisplay),
                    color = MaterialTheme.colorScheme.primary,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
            }
            if (chartPoints.any { it.amountCents > 0L }) {
                ReportsTrendLineChart(points = chartPoints, currencyDisplay = currencyDisplay)
            } else {
                Text(
                    text = "这个月份还没有可画出的确认支出。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
            }
            if (overview.merchantRanking.isNotEmpty()) {
                RankingBlock(
                    title = "商家排行",
                    rows = overview.merchantRanking.take(5),
                    currencyDisplay = currencyDisplay,
                )
            }
            if (overview.categoryComparison.isNotEmpty()) {
                CategoryComparisonBlock(rows = overview.categoryComparison.take(5), currencyDisplay = currencyDisplay)
            }
        }
    }
}

@Composable
internal fun GoalsSummaryCard(
    goals: List<Goal>,
    modifier: Modifier = Modifier,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val visibleGoals = goals.filterNot { it.isArchived }.take(4)

    AppGlassCard(modifier = modifier, containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("月度目标", style = MaterialTheme.typography.titleMedium, fontWeight = AppTextHierarchy.heading.weight)
            if (visibleGoals.isEmpty()) {
                Text(
                    text = "本月还没有目标。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
            } else {
                visibleGoals.forEach { goal ->
                    GoalProgressRow(goal, currencyDisplay)
                }
            }
        }
    }
}

@Composable
private fun ReportsTrendLineChart(
    points: List<ReportTrendChartPoint>,
    currencyDisplay: CurrencyDisplay,
) {
    val chartTokens = LocalChartTokens.current
    val modelProducer = remember { CartesianChartModelProducer() }
    val labels = remember(points) { points.map { it.label } }
    val bottomAxisValueFormatter = CartesianValueFormatter { _, value, _ ->
        labels.getOrNull(value.toInt()).orEmpty()
    }
    val startAxisValueFormatter = CartesianValueFormatter { _, value, _ ->
        compactAmountCentsLabel(value.toLong(), currencyDisplay)
    }
    val lineColor = chartTokens.series.firstOrNull() ?: MaterialTheme.colorScheme.primary

    LaunchedEffect(points) {
        modelProducer.runTransaction {
            lineSeries {
                series(
                    x = points.map { it.x },
                    y = points.map { it.amountCents },
                )
            }
        }
    }

    CartesianChartHost(
        chart = rememberCartesianChart(
            rememberLineCartesianLayer(
                lineProvider = LineCartesianLayer.LineProvider.series(
                    LineCartesianLayer.rememberLine(
                        fill = LineCartesianLayer.LineFill.single(Fill(lineColor)),
                        areaFill = LineCartesianLayer.AreaFill.single(
                            Fill(
                                Brush.verticalGradient(
                                    listOf(lineColor.copy(alpha = 0.34f), lineColor.copy(alpha = 0.02f)),
                                ),
                            ),
                        ),
                        interpolator = LineCartesianLayer.Interpolator.catmullRom(),
                    ),
                ),
            ),
            startAxis = VerticalAxis.rememberStart(valueFormatter = startAxisValueFormatter),
            bottomAxis = HorizontalAxis.rememberBottom(valueFormatter = bottomAxisValueFormatter),
        ),
        modelProducer = modelProducer,
        modifier = Modifier
            .fillMaxWidth()
            .height(180.dp),
        scrollState = rememberVicoScrollState(scrollEnabled = false),
    )
}

@Composable
private fun RankingBlock(
    title: String,
    rows: List<ReportMerchantRanking>,
    currencyDisplay: CurrencyDisplay,
) {
    val maxAmount = rows.maxOfOrNull { it.amountCents } ?: 0L
    Column(verticalArrangement = Arrangement.spacedBy(9.dp)) {
        Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = AppTextHierarchy.body.weight)
        rows.forEach { row ->
            AmountBarRow(
                label = row.merchant.ifBlank { "未填写商家" },
                amountCents = row.amountCents,
                count = row.count,
                maxAmountCents = maxAmount,
                currencyDisplay = currencyDisplay,
            )
        }
    }
}

@Composable
private fun CategoryComparisonBlock(
    rows: List<ReportCategoryComparison>,
    currencyDisplay: CurrencyDisplay,
) {
    Column(verticalArrangement = Arrangement.spacedBy(9.dp)) {
        Text("分类环比", style = MaterialTheme.typography.titleSmall, fontWeight = AppTextHierarchy.body.weight)
        rows.forEach { row ->
            val deltaText = when {
                row.deltaAmountCents > 0L -> "多 ${formatDisplayAmount(row.deltaAmountCents, currencyDisplay)}"
                row.deltaAmountCents < 0L -> "少 ${formatDisplayAmount(abs(row.deltaAmountCents), currencyDisplay)}"
                else -> "持平"
            }
            AmountBarRow(
                label = row.category,
                amountCents = row.amountCents,
                count = row.count,
                maxAmountCents = rows.maxOfOrNull { it.amountCents } ?: 0L,
                currencyDisplay = currencyDisplay,
                trailingText = deltaText,
            )
        }
    }
}

@Composable
private fun AmountBarRow(
    label: String,
    amountCents: Long,
    count: Int,
    maxAmountCents: Long,
    currencyDisplay: CurrencyDisplay,
    trailingText: String = "${count} 笔",
) {
    val chartTokens = LocalChartTokens.current
    val progress = if (maxAmountCents > 0L) {
        (amountCents.toFloat() / maxAmountCents.toFloat()).coerceIn(0f, 1f)
    } else {
        0f
    }
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = label,
                modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.bodyMedium,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = formatDisplayAmount(amountCents, currencyDisplay),
                style = MaterialTheme.typography.labelLarge,
                fontWeight = AppTextHierarchy.body.weight,
            )
            Text(
                text = trailingText,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelSmall,
            )
        }
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(7.dp)
                .clip(RoundedCornerShape(999.dp))
                .background(chartTokens.grid),
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(progress)
                    .height(7.dp)
                    .clip(RoundedCornerShape(999.dp))
                    .background(chartTokens.series.getOrElse(1) { MaterialTheme.colorScheme.primary }),
            )
        }
    }
}

@Composable
private fun GoalProgressRow(
    goal: Goal,
    currencyDisplay: CurrencyDisplay,
) {
    val chartTokens = LocalChartTokens.current
    val color = if (goal.isOverLimit) chartTokens.overspend else chartTokens.series.first()
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text = goal.name,
                modifier = Modifier.weight(1f),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                style = MaterialTheme.typography.bodyMedium,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = "${goal.progressPercent.coerceAtLeast(0)}%",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelLarge,
                fontWeight = AppTextHierarchy.body.weight,
            )
        }
        LinearProgressIndicator(
            progress = { goal.progress.coerceIn(0f, 1f) },
            modifier = Modifier
                .fillMaxWidth()
                .height(8.dp)
                .clip(RoundedCornerShape(999.dp)),
            color = color,
            trackColor = chartTokens.grid,
        )
        Text(
            text = "${goal.category ?: "总支出"} · 已花 ${formatDisplayAmount(goal.spentAmountCents, currencyDisplay)} · 剩 ${formatDisplayAmount(goal.remainingAmountCents, currencyDisplay)}",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

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

internal fun compactAmountCentsLabel(
    amountCents: Long,
    currencyDisplay: CurrencyDisplay = CurrencyDisplay.Base,
): String {
    val sign = if (amountCents < 0L) "-" else ""
    val currency = currencyDisplay.homeCurrency
    val minorAmount = amountCents
    val absMinor = abs(minorAmount)
    val symbol = currency.symbol
    val majorDivisor = if (currency.noFractionDigits) 1L else 100L
    val tenThousandMajorMinor = majorDivisor * 10_000L
    return when {
        absMinor >= tenThousandMajorMinor -> "${sign}${symbol}${decimal(absMinor, tenThousandMajorMinor)}万"
        absMinor >= majorDivisor * 1_000L -> "${sign}${symbol}${decimal(absMinor, majorDivisor * 1_000L)}k"
        else -> "${sign}${symbol}${decimal(absMinor, majorDivisor)}"
    }
}

private fun decimal(value: Long, divisor: Long): String =
    BigDecimal(value)
        .divide(BigDecimal(divisor), 1, RoundingMode.HALF_UP)
        .stripTrailingZeros()
        .toPlainString()

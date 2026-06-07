package com.ticketbox.ui.screens.stats

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.patrykandpatrick.vico.compose.cartesian.CartesianChartHost
import com.patrykandpatrick.vico.compose.cartesian.axis.HorizontalAxis
import com.patrykandpatrick.vico.compose.cartesian.axis.VerticalAxis
import com.patrykandpatrick.vico.compose.cartesian.data.CartesianChartModelProducer
import com.patrykandpatrick.vico.compose.cartesian.data.CartesianValueFormatter
import com.patrykandpatrick.vico.compose.cartesian.data.columnSeries
import com.patrykandpatrick.vico.compose.cartesian.layer.ColumnCartesianLayer
import com.patrykandpatrick.vico.compose.cartesian.layer.rememberColumnCartesianLayer
import com.patrykandpatrick.vico.compose.cartesian.rememberCartesianChart
import com.patrykandpatrick.vico.compose.cartesian.rememberVicoScrollState
import com.patrykandpatrick.vico.compose.common.Fill
import com.patrykandpatrick.vico.compose.common.component.rememberLineComponent
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalProgressState
import com.ticketbox.domain.model.ReportCategoryComparison
import com.ticketbox.domain.model.ReportMerchantRanking
import com.ticketbox.domain.model.ReportTrendPoint
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.R
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.design.AppMotion
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalChartTokens
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.AppTextHierarchy
import java.math.BigDecimal
import java.math.RoundingMode
import kotlin.math.abs

private object ReportsInsightLayout {
    val GoalRingSize = 58.dp
    val GoalRingStroke = 5.dp
    const val GoalRingStartAngle = -90f
}

@Composable
internal fun ReportsInsightCard(
    overview: ReportsOverview,
    modifier: Modifier = Modifier,
) {
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
                    Text(
                        stringResource(R.string.stats_reports_chart_title),
                        style = MaterialTheme.typography.titleMedium,
                        fontWeight = AppTextHierarchy.heading.weight,
                    )
                    Text(
                        text = stringResource(R.string.stats_reports_chart_subtitle, overview.month, overview.count),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
                Text(
                    text = formatAmount(overview.totalAmountCents),
                    color = MaterialTheme.colorScheme.onSurface,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
            }
            val nonZeroDays = chartPoints.count { it.amountCents > 0L }
            when {
                nonZeroDays == 0 -> Text(
                    text = stringResource(R.string.stats_reports_chart_empty),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
                // 稀疏态：1–2 天有支出时柱状信息量太低，降级成文案而非画误导图（区分 空态/稀疏态/正常态）。
                nonZeroDays <= 2 -> Text(
                    text = stringResource(R.string.stats_reports_chart_sparse, nonZeroDays),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
                else -> ReportsTrendColumnChart(points = chartPoints)
            }
            if (overview.merchantRanking.isNotEmpty()) {
                RankingBlock(
                    title = stringResource(R.string.stats_reports_merchant_ranking_title),
                    rows = overview.merchantRanking.take(5),
                )
            }
            if (overview.categoryComparison.isNotEmpty()) {
                CategoryComparisonBlock(rows = overview.categoryComparison.take(5))
            }
        }
    }
}

@Composable
internal fun GoalsSummaryCard(
    goals: List<Goal>,
    modifier: Modifier = Modifier,
) {
    val visibleGoals = goals.filterNot { it.isArchived }.take(4)

    AppGlassCard(modifier = modifier, containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text(
                stringResource(R.string.stats_reports_goals_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            if (visibleGoals.isEmpty()) {
                Text(
                    text = stringResource(R.string.stats_reports_goals_empty),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
            } else {
                visibleGoals.forEach { goal ->
                    GoalProgressRow(goal)
                }
            }
        }
    }
}

@Composable
private fun ReportsTrendColumnChart(points: List<ReportTrendChartPoint>) {
    val chartTokens = LocalChartTokens.current
    val modelProducer = remember { CartesianChartModelProducer() }
    val labels = remember(points) { points.map { it.label } }
    val bottomAxisValueFormatter = CartesianValueFormatter { _, value, _ ->
        labels.getOrNull(value.toInt()).orEmpty()
    }
    val startAxisValueFormatter = CartesianValueFormatter { _, value, _ ->
        compactAmountCentsLabel(value.toLong())
    }
    val columnColor = chartTokens.series.firstOrNull() ?: MaterialTheme.colorScheme.primary

    LaunchedEffect(points) {
        modelProducer.runTransaction {
            // 按天支出是离散事件：用柱状强调每天的量级，不用折线（平滑折线会暗示天与天之间连续变化）。
            columnSeries {
                series(
                    x = points.map { it.x },
                    y = points.map { it.amountCents },
                )
            }
        }
    }

    CartesianChartHost(
        chart = rememberCartesianChart(
            rememberColumnCartesianLayer(
                columnProvider = ColumnCartesianLayer.ColumnProvider.series(
                    rememberLineComponent(
                        fill = Fill(columnColor),
                        thickness = 10.dp,
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
) {
    val maxAmount = rows.maxOfOrNull { it.amountCents } ?: 0L
    val merchantFallback = stringResource(R.string.stats_reports_merchant_fallback)
    Column(verticalArrangement = Arrangement.spacedBy(9.dp)) {
        Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = AppTextHierarchy.body.weight)
        rows.forEach { row ->
            AmountBarRow(
                label = row.merchant.ifBlank { merchantFallback },
                amountCents = row.amountCents,
                count = row.count,
                maxAmountCents = maxAmount,
            )
        }
    }
}

@Composable
private fun CategoryComparisonBlock(rows: List<ReportCategoryComparison>) {
    Column(verticalArrangement = Arrangement.spacedBy(9.dp)) {
        Text(
            stringResource(R.string.stats_reports_category_comparison_title),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.body.weight,
        )
        rows.forEach { row ->
            val deltaText = when {
                row.deltaAmountCents > 0L -> stringResource(R.string.stats_reports_category_delta_more, formatAmount(row.deltaAmountCents))
                row.deltaAmountCents < 0L -> stringResource(R.string.stats_reports_category_delta_less, formatAmount(abs(row.deltaAmountCents)))
                else -> stringResource(R.string.stats_reports_category_delta_flat)
            }
            AmountBarRow(
                label = row.category,
                amountCents = row.amountCents,
                count = row.count,
                maxAmountCents = rows.maxOfOrNull { it.amountCents } ?: 0L,
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
    trailingText: String = stringResource(R.string.stats_reports_bar_count, count),
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
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
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
                text = formatAmount(amountCents),
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
private fun GoalProgressRow(goal: Goal) {
    val stateTokens = LocalStateTokens.current
    val tone = when (goal.progressState) {
        GoalProgressState.OverLimit -> stateTokens.danger
        GoalProgressState.NearLimit -> stateTokens.warn
        GoalProgressState.OnTrack -> stateTokens.success
        GoalProgressState.Archived -> stateTokens.neutral
        GoalProgressState.Idle -> stateTokens.info
    }

    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        GoalProgressRing(
            progress = goal.progress,
            progressPercent = goal.progressPercent,
            color = tone.fg,
            trackColor = tone.bg,
        )
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
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
                    text = formatAmount(goal.targetAmountCents),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelLarge,
                    fontWeight = AppTextHierarchy.body.weight,
                )
            }
            Text(
                text = stringResource(
                    R.string.stats_reports_goal_progress,
                    goal.category ?: stringResource(R.string.stats_reports_goal_total),
                    formatAmount(goal.spentAmountCents),
                    formatAmount(goal.remainingAmountCents),
                ),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelSmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

@Composable
private fun GoalProgressRing(
    progress: Float,
    progressPercent: Int,
    color: Color,
    trackColor: Color,
    modifier: Modifier = Modifier,
) {
    val animatedProgress by animateFloatAsState(
        targetValue = progress.coerceIn(0f, 1f),
        animationSpec = tween(durationMillis = AppMotion.normalMillis),
        label = "goal-progress-ring",
    )

    Box(
        modifier = modifier.size(ReportsInsightLayout.GoalRingSize),
        contentAlignment = Alignment.Center,
    ) {
        Canvas(modifier = Modifier.size(ReportsInsightLayout.GoalRingSize)) {
            val strokeWidth = ReportsInsightLayout.GoalRingStroke.toPx()
            val arcOffset = strokeWidth / 2f
            val arcSize = Size(size.width - strokeWidth, size.height - strokeWidth)
            drawCircle(
                color = trackColor,
                radius = (size.minDimension - strokeWidth) / 2f,
                style = Stroke(width = strokeWidth, cap = StrokeCap.Round),
            )
            drawArc(
                color = color,
                startAngle = ReportsInsightLayout.GoalRingStartAngle,
                sweepAngle = animatedProgress * 360f,
                useCenter = false,
                topLeft = Offset(arcOffset, arcOffset),
                size = arcSize,
                style = Stroke(width = strokeWidth, cap = StrokeCap.Round),
            )
        }
        Text(
            text = stringResource(R.string.stats_reports_goal_percent, progressPercent.coerceAtLeast(0)),
            color = color,
            style = MaterialTheme.typography.labelSmall,
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
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

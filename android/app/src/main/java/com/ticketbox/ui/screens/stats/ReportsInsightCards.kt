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
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.patrykandpatrick.vico.compose.cartesian.CartesianChartHost
import com.patrykandpatrick.vico.compose.cartesian.axis.HorizontalAxis
import com.patrykandpatrick.vico.compose.cartesian.axis.VerticalAxis
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisLabelComponent
import com.patrykandpatrick.vico.compose.cartesian.axis.rememberAxisLineComponent
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
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportMerchantRanking
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.R
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.AppSegmentedControl
import com.ticketbox.ui.components.AppSegmentedItem
import com.ticketbox.ui.components.formatAmount
import com.ticketbox.ui.design.AppMotion
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalChartTokens
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.tabularNum
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
    // 轴3 粒度切换:selected 用服务端回显(overview.granularity),切换交给 VM 重拉。
    // 默认 no-op 保旧调用方/预览。
    onGranularityChange: (ReportGranularity) -> Unit = {},
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
                    style = MaterialTheme.typography.titleSmall.tabularNum(),
                    fontWeight = AppTextHierarchy.heading.weight,
                )
            }
            // 轴3 粒度切换:日/周两档。单月报表内 Month 粒度只有一桶,无图可画,刻意不给。
            AppSegmentedControl(
                options = listOf(
                    AppSegmentedItem(ReportGranularity.Day, stringResource(R.string.stats_reports_granularity_day)),
                    AppSegmentedItem(ReportGranularity.Week, stringResource(R.string.stats_reports_granularity_week)),
                ),
                selectedValue = if (overview.granularity == ReportGranularity.Week) {
                    ReportGranularity.Week
                } else {
                    ReportGranularity.Day
                },
                onValueChange = onGranularityChange,
            )
            val nonZeroDays = chartPoints.count { it.amountCents > 0L }
            when {
                nonZeroDays == 0 -> Text(
                    text = stringResource(R.string.stats_reports_chart_empty),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
                // 稀疏态：1–2 桶有支出时柱状信息量太低，降级成文案而非画误导图（区分 空态/稀疏态/正常态）。
                // 周粒度天然只有 4-5 桶,2 桶以下同样按稀疏降级,口径一致。
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

    // WCAG 1.1.1:Vico 柱图对 TalkBack 是不透明画布,给图表节点补文本替代(逐档「标签 金额」)。
    // 零额档不逐日朗读,汇总成「其余 N 档无支出」,避免日粒度下读出 ~30 个 ¥0.00(纯函数见 trendChartA11y)。
    val trendA11yData = remember(points) { trendChartA11y(points) }
    val trendA11y = if (trendA11yData.zeroBuckets > 0) {
        stringResource(R.string.stats_reports_chart_a11y_with_zeros, trendA11yData.listed, trendA11yData.zeroBuckets)
    } else {
        stringResource(R.string.stats_reports_chart_a11y, trendA11yData.listed)
    }

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

    // Skin-themed axes (was M3 default): consume the ChartTokens axis/axisLabel
    // (previously dead) so axis line + labels match the active skin's chart palette.
    val axisLineComponent = rememberAxisLineComponent(fill = Fill(chartTokens.axis))
    val axisLabelComponent = rememberAxisLabelComponent(style = TextStyle(color = chartTokens.axisLabel, fontSize = 12.sp))

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
            startAxis = VerticalAxis.rememberStart(line = axisLineComponent, label = axisLabelComponent, valueFormatter = startAxisValueFormatter),
            bottomAxis = HorizontalAxis.rememberBottom(line = axisLineComponent, label = axisLabelComponent, valueFormatter = bottomAxisValueFormatter),
        ),
        modelProducer = modelProducer,
        modifier = Modifier
            .fillMaxWidth()
            .height(180.dp)
            .semantics { contentDescription = trendA11y },
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
        // 轴3 三柱对比:本月 vs 上月 vs 去年同月 grouped columns 给「形状」,下面的行制保留精确值。
        // 两月皆零的行画不出对比,纯函数已过滤;全被滤光时只剩行制(不画空图)。
        val chartRows = remember(rows) { categoryComparisonChartRows(rows) }
        if (chartRows.size >= 2) {
            CategoryComparisonGroupedChart(rows = chartRows)
            ComparisonLegend()
        }
        rows.forEach { row ->
            val deltaText = when {
                row.yearOverYearDeltaAmountCents > 0L -> stringResource(
                    R.string.stats_reports_category_yoy_more,
                    formatAmount(row.yearOverYearDeltaAmountCents),
                )
                row.yearOverYearDeltaAmountCents < 0L -> stringResource(
                    R.string.stats_reports_category_yoy_less,
                    formatAmount(abs(row.yearOverYearDeltaAmountCents)),
                )
                else -> stringResource(R.string.stats_reports_category_yoy_flat)
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

/**
 * 轴3 三柱对比:本月/上月/去年同月三 series 的 grouped column chart(Vico 多 series 列层默认分组)。
 * x=分类索引,bottom 轴标分类名;series 色取 chart tokens 前三槽(与图例同源)。
 */
@Composable
private fun CategoryComparisonGroupedChart(rows: List<CategoryComparisonChartRow>) {
    val chartTokens = LocalChartTokens.current
    val modelProducer = remember { CartesianChartModelProducer() }
    val labels = remember(rows) { rows.map { it.category } }
    val bottomAxisValueFormatter = CartesianValueFormatter { _, value, _ ->
        labels.getOrNull(value.toInt()).orEmpty()
    }
    val startAxisValueFormatter = CartesianValueFormatter { _, value, _ ->
        compactAmountCentsLabel(value.toLong())
    }
    val currentColor = chartTokens.series.firstOrNull() ?: MaterialTheme.colorScheme.primary
    val previousColor = chartTokens.series.getOrElse(1) { MaterialTheme.colorScheme.secondary }
    val yearOverYearColor = chartTokens.series.getOrElse(2) { MaterialTheme.colorScheme.tertiary }

    // WCAG 1.1.1:同趋势图,给三柱对比补文本替代——逐分类朗读「分类 本月X 上月Y 去年同月Z」,
    // 三个图例标签复用图例同源串,金额走 formatAmount。
    val thisMonthLabel = stringResource(R.string.stats_reports_legend_current_month)
    val lastMonthLabel = stringResource(R.string.stats_reports_legend_previous_month)
    val yearOverYearLabel = stringResource(R.string.stats_reports_legend_year_over_year_month)
    val comparisonA11yBody = remember(rows, thisMonthLabel, lastMonthLabel, yearOverYearLabel) {
        comparisonChartA11yBody(rows, thisMonthLabel, lastMonthLabel, yearOverYearLabel)
    }
    val comparisonA11y = stringResource(R.string.stats_reports_comparison_a11y, comparisonA11yBody)

    LaunchedEffect(rows) {
        modelProducer.runTransaction {
            columnSeries {
                series(x = rows.indices.map { it }, y = rows.map { it.currentAmountCents })
                series(x = rows.indices.map { it }, y = rows.map { it.previousAmountCents })
                series(x = rows.indices.map { it }, y = rows.map { it.yearOverYearAmountCents })
            }
        }
    }

    val axisLineComponent = rememberAxisLineComponent(fill = Fill(chartTokens.axis))
    val axisLabelComponent = rememberAxisLabelComponent(style = TextStyle(color = chartTokens.axisLabel, fontSize = 12.sp))

    CartesianChartHost(
        chart = rememberCartesianChart(
            rememberColumnCartesianLayer(
                columnProvider = ColumnCartesianLayer.ColumnProvider.series(
                    rememberLineComponent(fill = Fill(currentColor), thickness = 8.dp),
                    rememberLineComponent(fill = Fill(previousColor), thickness = 8.dp),
                    rememberLineComponent(fill = Fill(yearOverYearColor), thickness = 8.dp),
                ),
            ),
            startAxis = VerticalAxis.rememberStart(line = axisLineComponent, label = axisLabelComponent, valueFormatter = startAxisValueFormatter),
            bottomAxis = HorizontalAxis.rememberBottom(line = axisLineComponent, label = axisLabelComponent, valueFormatter = bottomAxisValueFormatter),
        ),
        modelProducer = modelProducer,
        modifier = Modifier
            .fillMaxWidth()
            .height(160.dp)
            .semantics { contentDescription = comparisonA11y },
        scrollState = rememberVicoScrollState(scrollEnabled = false),
    )
}

/** 图例:三色点+「本月/上月/去年同月」,与 grouped chart 的 series 色同源(chart tokens 前三槽)。 */
@Composable
private fun ComparisonLegend() {
    val chartTokens = LocalChartTokens.current
    val currentColor = chartTokens.series.firstOrNull() ?: MaterialTheme.colorScheme.primary
    val previousColor = chartTokens.series.getOrElse(1) { MaterialTheme.colorScheme.secondary }
    val yearOverYearColor = chartTokens.series.getOrElse(2) { MaterialTheme.colorScheme.tertiary }
    Row(
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        LegendDot(color = currentColor, label = stringResource(R.string.stats_reports_legend_current_month))
        LegendDot(color = previousColor, label = stringResource(R.string.stats_reports_legend_previous_month))
        LegendDot(
            color = yearOverYearColor,
            label = stringResource(R.string.stats_reports_legend_year_over_year_month),
        )
    }
}

@Composable
private fun LegendDot(color: Color, label: String) {
    Row(
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(
            modifier = Modifier
                .size(8.dp)
                .clip(RoundedCornerShape(999.dp))
                .background(color),
        )
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
        )
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
                style = MaterialTheme.typography.labelLarge.tabularNum(),
                fontWeight = AppTextHierarchy.body.weight,
            )
            Text(
                text = trailingText,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelSmall.tabularNum(),
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
                    style = MaterialTheme.typography.labelLarge.tabularNum(),
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
                style = MaterialTheme.typography.labelSmall.tabularNum(),
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

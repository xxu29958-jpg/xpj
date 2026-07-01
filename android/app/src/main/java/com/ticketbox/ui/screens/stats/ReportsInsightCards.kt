package com.ticketbox.ui.screens.stats

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
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.domain.model.DailySpend
import com.ticketbox.domain.model.ReportCategoryComparison
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportMerchantRanking
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.R
import com.ticketbox.ui.components.AppSegmentedControl
import com.ticketbox.ui.components.AppSegmentedItem
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalChartTokens
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.tabularNum
import kotlin.math.abs

@Composable
internal fun ReportsInsightCard(
    overview: ReportsOverview,
    modifier: Modifier = Modifier,
    recentTrend: List<DailySpend> = emptyList(),
    onGranularityChange: (ReportGranularity) -> Unit = {},
) {
    val chartPoints = remember(overview.trend) { reportTrendChartPoints(overview.trend) }

    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        ReportsChartPanel(
            overview = overview,
            chartPoints = chartPoints,
            recentTrend = recentTrend,
            onGranularityChange = onGranularityChange,
        )
        if (overview.merchantRanking.isNotEmpty()) {
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
            RankingBlock(
                title = stringResource(R.string.stats_reports_merchant_ranking_title),
                rows = overview.merchantRanking.take(5),
            )
        }
        if (overview.categoryComparison.isNotEmpty()) {
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
            CategoryComparisonBlock(rows = overview.categoryComparison.take(5))
        }
    }
}

@Composable
private fun ReportsChartPanel(
    overview: ReportsOverview,
    chartPoints: List<ReportTrendChartPoint>,
    recentTrend: List<DailySpend>,
    onGranularityChange: (ReportGranularity) -> Unit,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight)) {
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
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
                text = formatDisplayAmount(overview.totalAmountCents, currencyDisplay),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.titleSmall.tabularNum(),
                fontWeight = AppTextHierarchy.heading.weight,
            )
        }
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
            nonZeroDays <= 2 -> ReportsSparseTrend(
                points = chartPoints,
                nonZeroDays = nonZeroDays,
            )
            else -> ReportsTrendFlowChart(points = chartPoints)
        }
        ReportsRecentWindowSummary(recentTrend = recentTrend)
    }
}

@Composable
private fun ReportsSparseTrend(
    points: List<ReportTrendChartPoint>,
    nonZeroDays: Int,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val sparseA11y = remember(points, currencyDisplay) {
        points
            .filter { it.amountCents > 0L }
            .joinToString(separator = "\uFF0C") {
                "${it.label} ${formatDisplayAmount(it.amountCents, currencyDisplay)}"
            }
    }
    Text(
        text = stringResource(R.string.stats_reports_chart_sparse, nonZeroDays),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodyMedium,
    )
    StatsSpendDistributionRows(
        points = points
            .filter { it.amountCents > 0L }
            .map { StatsSpendChartPoint(label = it.label, amountCents = it.amountCents) },
        spec = StatsSpendDistributionSpec(
            maxRows = 2,
            sortByAmount = false,
            includeZeros = false,
            contentDescription = sparseA11y,
        ),
    )
}

@Composable
private fun RankingBlock(
    title: String,
    rows: List<ReportMerchantRanking>,
) {
    val maxAmount = rows.maxOfOrNull { it.amountCents } ?: 0L
    val merchantFallback = stringResource(R.string.stats_reports_merchant_fallback)
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap + AppSpacing.tinyGap)) {
        Text(title, style = MaterialTheme.typography.titleSmall, fontWeight = AppTextHierarchy.body.weight)
        rows.forEach { row ->
            AmountBarRow(
                label = row.merchant.ifBlank { merchantFallback },
                amountCents = row.amountCents,
                maxAmountCents = maxAmount,
                trailingText = stringResource(R.string.stats_reports_bar_count, row.count),
            )
        }
    }
}

@Composable
private fun CategoryComparisonBlock(rows: List<ReportCategoryComparison>) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val maxAmount = rows.maxOfOrNull { it.amountCents } ?: 0L
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap + AppSpacing.tinyGap)) {
        Text(
            stringResource(R.string.stats_reports_category_comparison_title),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.body.weight,
        )
        // 轴3 三柱对比:本月 vs 上月 vs 去年同月 grouped columns 给「形状」,下面的行制保留精确值。
        // 两月皆零的行画不出对比,纯函数已过滤;全被滤光时只剩行制(不画空图)。
        val chartRows = remember(rows) { categoryComparisonChartRows(rows) }
        val hasComparisonBaseline = remember(chartRows) {
            chartRows.any { it.previousAmountCents > 0L || it.yearOverYearAmountCents > 0L }
        }
        if (chartRows.size >= 2 && hasComparisonBaseline) {
            CategoryComparisonGroupedChart(rows = chartRows)
            ComparisonLegend()
        }
        rows.forEach { row ->
            val deltaText = when {
                row.yearOverYearDeltaAmountCents > 0L -> stringResource(
                    R.string.stats_reports_category_yoy_more,
                    formatDisplayAmount(row.yearOverYearDeltaAmountCents, currencyDisplay),
                )
                row.yearOverYearDeltaAmountCents < 0L -> stringResource(
                    R.string.stats_reports_category_yoy_less,
                    formatDisplayAmount(abs(row.yearOverYearDeltaAmountCents), currencyDisplay),
                )
                else -> stringResource(R.string.stats_reports_category_yoy_flat)
            }
            AmountBarRow(
                label = row.category,
                amountCents = row.amountCents,
                maxAmountCents = maxAmount,
                trailingText = deltaText,
                supportingText = stringResource(
                    R.string.stats_reports_category_comparison_values,
                    formatDisplayAmount(row.previousAmountCents, currencyDisplay),
                    formatDisplayAmount(row.yearOverYearAmountCents, currencyDisplay),
                ),
            )
        }
    }
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
                .size(AppSpacing.chipGap)
                .clip(RoundedCornerShape(AppRadius.pill))
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
    maxAmountCents: Long,
    trailingText: String,
    supportingText: String? = null,
) {
    val chartTokens = LocalChartTokens.current
    val currencyDisplay = LocalCurrencyDisplay.current
    val progress = if (maxAmountCents > 0L) {
        (amountCents.toFloat() / maxAmountCents.toFloat()).coerceIn(0f, 1f)
    } else {
        0f
    }
    val fillColor = chartTokens.series.firstOrNull() ?: MaterialTheme.colorScheme.primary
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap + AppSpacing.tinyGap)) {
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
                text = formatDisplayAmount(amountCents, currencyDisplay),
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
                .height(AppSpacing.miniGap)
                .clip(RoundedCornerShape(AppRadius.pill))
                .background(chartTokens.grid),
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth(progress)
                    .height(AppSpacing.miniGap)
                    .clip(RoundedCornerShape(AppRadius.pill))
                    .background(fillColor.copy(alpha = AppAlpha.heavy)),
            )
        }
        supportingText?.let {
            Text(
                text = it,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelSmall.tabularNum(),
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
    }
}

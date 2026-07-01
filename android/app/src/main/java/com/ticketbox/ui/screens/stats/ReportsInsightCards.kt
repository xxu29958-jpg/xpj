package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.domain.model.DailySpend
import com.ticketbox.domain.model.ReportCategoryComparison
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.R
import com.ticketbox.ui.components.AppSegmentedControl
import com.ticketbox.ui.components.AppSegmentedItem
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalChartTokens
import com.ticketbox.ui.design.tabularNum
import kotlin.math.abs

@Composable
internal fun ReportsInsightCard(
    overview: ReportsOverview,
    modifier: Modifier = Modifier,
    recentTrend: List<DailySpend> = emptyList(),
    onGranularityChange: (ReportGranularity) -> Unit = {},
) {
    val model = remember(overview) { reportsAnswerModel(overview) }
    val hasCurrentSpend = model.count > 0 && model.totalAmountCents > 0L

    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        ReportsAnswerHeader(model = model)
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
        ReportsChartPanel(
            model = model,
            recentTrend = recentTrend,
            onGranularityChange = onGranularityChange,
        )
        if (hasCurrentSpend && overview.merchantRanking.isNotEmpty()) {
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
            MerchantRankingBlock(
                rows = overview.merchantRanking.take(5),
                rankingMetric = overview.rankingMetric,
            )
        }
        if (hasCurrentSpend && overview.categoryComparison.isNotEmpty()) {
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
            CategoryComparisonBlock(rows = overview.categoryComparison.take(5))
        }
    }
}

@Composable
private fun ReportsChartPanel(
    model: ReportsAnswerModel,
    recentTrend: List<DailySpend>,
    onGranularityChange: (ReportGranularity) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight)) {
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                Text(
                    stringResource(R.string.stats_reports_trend_title),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
                Text(
                    text = stringResource(R.string.stats_reports_trend_subtitle),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
        AppSegmentedControl(
            options = listOf(
                AppSegmentedItem(ReportGranularity.Day, stringResource(R.string.stats_reports_granularity_day)),
                AppSegmentedItem(ReportGranularity.Week, stringResource(R.string.stats_reports_granularity_week)),
            ),
            selectedValue = if (model.granularity == ReportGranularity.Week) {
                ReportGranularity.Week
            } else {
                ReportGranularity.Day
            },
            onValueChange = onGranularityChange,
        )
        when (model.trendEvidence.mode) {
            ReportsTrendMode.Empty -> Text(
                text = stringResource(R.string.stats_reports_chart_empty),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
            )
            ReportsTrendMode.Sparse -> ReportsSparseTrend(
                points = model.trendPoints,
                nonZeroDays = model.trendEvidence.positiveBucketCount,
            )
            ReportsTrendMode.DominantPeak,
            ReportsTrendMode.Chart,
            -> ReportsTrendFlowChart(points = model.trendPoints)
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

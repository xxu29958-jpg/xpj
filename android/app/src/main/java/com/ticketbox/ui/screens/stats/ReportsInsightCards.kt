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
import com.ticketbox.domain.model.ReportRankingMetric
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.R
import com.ticketbox.ui.components.AppAdaptiveAmountRowStyle
import com.ticketbox.ui.components.AppAdaptiveEditAmountRow
import com.ticketbox.ui.components.AppSegmentedControl
import com.ticketbox.ui.components.AppSegmentedItem
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppAmountRole
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
    onGranularityChange: (ReportGranularity) -> Unit = {},
    onRankingMetricChange: (ReportRankingMetric) -> Unit = {},
) {
    val model = remember(overview) { reportsAnswerModel(overview) }
    val recentTrend = remember(overview) { reportsRecentWindowTrend(overview) }
    val hasCurrentSpend = model.count > 0 && model.totalAmountCents > 0L

    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        ReportsChartPanel(
            model = model,
            recentTrend = recentTrend,
            onGranularityChange = onGranularityChange,
        )
        if (hasCurrentSpend && overview.merchantRanking.isNotEmpty()) {
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
            MerchantRankingBlock(
                rows = overview.merchantRanking,
                rankingMetric = overview.rankingMetric,
                onRankingMetricChange = onRankingMetricChange,
            )
        }
        if (hasCurrentSpend && overview.categoryComparison.isNotEmpty()) {
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
            CategoryComparisonBlock(rows = overview.categoryComparison)
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
        ReportsRecentWindowSummary(
            recentTrend = recentTrend,
            avoidRepeatedSparseRows = model.trendEvidence.mode == ReportsTrendMode.Sparse,
        )
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
    StatsSparseSpendRows(
        points = points
            .filter { it.amountCents > 0L }
            .map { StatsSpendChartPoint(label = it.label, amountCents = it.amountCents) },
        contentDescription = sparseA11y,
    )
}

@Composable
private fun CategoryComparisonBlock(rows: List<ReportCategoryComparison>) {
    val chartRows = remember(rows) { categoryComparisonChartRows(rows) }
    val maxAmount = chartRows.maxOfOrNull { it.currentAmountCents } ?: 0L
    val titleRes = when (categoryComparisonMode(chartRows)) {
        CategoryComparisonMode.Comparison -> R.string.stats_reports_category_comparison_title
        CategoryComparisonMode.CurrentOnly -> R.string.stats_reports_category_current_title
    }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap + AppSpacing.tinyGap)) {
        Text(
            stringResource(titleRes),
            style = MaterialTheme.typography.titleSmall,
            fontWeight = AppTextHierarchy.body.weight,
        )
        chartRows.forEach { row ->
            AmountBarRow(
                label = row.category,
                amountCents = row.currentAmountCents,
                maxAmountCents = maxAmount,
                trailingText = categoryYearOverYearText(row),
                supportingText = categoryComparisonValues(row),
            )
        }
    }
}

@Composable
private fun categoryYearOverYearText(row: CategoryComparisonChartRow): String? {
    if (!row.hasYearOverYear) return null
    val currencyDisplay = LocalCurrencyDisplay.current
    val deltaAmountCents = row.currentAmountCents - row.yearOverYearAmountCents
    return when {
        deltaAmountCents > 0L -> stringResource(
            R.string.stats_reports_category_yoy_more,
            formatDisplayAmount(deltaAmountCents, currencyDisplay),
        )
        deltaAmountCents < 0L -> stringResource(
            R.string.stats_reports_category_yoy_less,
            formatDisplayAmount(abs(deltaAmountCents), currencyDisplay),
        )
        else -> stringResource(R.string.stats_reports_category_yoy_flat)
    }
}

@Composable
private fun categoryComparisonValues(row: CategoryComparisonChartRow): String? {
    val currencyDisplay = LocalCurrencyDisplay.current
    return when {
        row.hasPrevious && row.hasYearOverYear -> stringResource(
            R.string.stats_reports_category_comparison_values,
            formatDisplayAmount(row.previousAmountCents, currencyDisplay),
            formatDisplayAmount(row.yearOverYearAmountCents, currencyDisplay),
        )
        row.hasPrevious -> stringResource(
            R.string.stats_reports_category_comparison_previous_only,
            formatDisplayAmount(row.previousAmountCents, currencyDisplay),
        )
        row.hasYearOverYear -> stringResource(
            R.string.stats_reports_category_comparison_yoy_only,
            formatDisplayAmount(row.yearOverYearAmountCents, currencyDisplay),
        )
        else -> null
    }
}

@Composable
private fun AmountBarRow(
    label: String,
    amountCents: Long,
    maxAmountCents: Long,
    trailingText: String?,
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
        AmountBarHeader(
            label = label,
            amountText = formatDisplayAmount(amountCents, currencyDisplay),
            trailingText = trailingText,
        )
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

@Composable
private fun AmountBarHeader(
    label: String,
    amountText: String,
    trailingText: String?,
) {
    AppAdaptiveEditAmountRow(
        amount = amountText,
        style = AppAdaptiveAmountRowStyle(
            role = AppAmountRole.Compact,
            trailingWeight = ReportsCategoryAmountWeight,
        ),
    ) {
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
            trailingText?.let {
                Text(
                    text = it,
                    modifier = Modifier.weight(ReportsCategoryTrailingWeight, fill = false),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelSmall.tabularNum(),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
            }
        }
    }
}

private const val ReportsCategoryAmountWeight = 0.58f
private const val ReportsCategoryTrailingWeight = 0.72f

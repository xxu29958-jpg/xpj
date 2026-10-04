package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import com.ticketbox.domain.model.CurrencyDisplay
import androidx.compose.runtime.remember
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.platform.testTag
import com.ticketbox.domain.model.ReportCategoryComparison
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.R
import com.ticketbox.ui.components.AppAdaptiveAmountRowStyle
import com.ticketbox.ui.components.AppAdaptiveEditAmountRow
import com.ticketbox.ui.components.AppSegmentedControl
import com.ticketbox.ui.components.AppSegmentedItem
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalChartTokens
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.ui.screens.StatsReportActions
import com.ticketbox.ui.screens.settings.SettingsEntryRow
import kotlin.math.abs

@Composable
internal fun ReportsInsightCard(
    overview: ReportsOverview,
    actions: StatsReportActions,
    modifier: Modifier = Modifier,
    exporting: Boolean = false,
    exportMessage: com.ticketbox.domain.model.UiText? = null,
) {
    val model = remember(overview) { reportsAnswerModel(overview) }
    val recentTrend = remember(overview) { reportsRecentWindowTrend(overview) }
    var showRankings by rememberSaveable { mutableStateOf(false) }
    var showComparisons by rememberSaveable { mutableStateOf(false) }
    var showData by rememberSaveable { mutableStateOf(false) }
    CompositionLocalProvider(LocalCurrencyDisplay provides CurrencyDisplay.forRecord(overview.homeCurrencyCode)) {
        if (showData) ReportsDataSheet(overview, exporting, exportMessage, actions.onExport) { showData = false }
        Column(
            modifier = modifier.fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap),
        ) {
            Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                Text(stringResource(R.string.reports_page_title), style = MaterialTheme.typography.headlineSmall,
                    fontWeight = AppTextHierarchy.hero.weight)
                Text(stringResource(R.string.reports_scope, displayMonthLabel(overview.month), overview.homeCurrencyCode),
                    color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodyMedium)
            }
            ReportsAnswerHeader(model = model)
            ReportsProjectionNotice(overview, actions)
            ReportsChartPanel(
                model = model,
                onGranularityChange = actions.onGranularityChange,
            )
            SettingsEntryRow(
                title = stringResource(R.string.reports_rankings_title),
                subtitle = stringResource(R.string.reports_rankings_description),
                icon = R.drawable.ic_lucide_chart_no_axes_combined,
                onClick = { showRankings = !showRankings }, expanded = showRankings,
            )
            if (showRankings) {
                ReportsMerchantCategoryFilter(overview, actions.onMerchantCategoryChange)
                MerchantRankingBlock(
                    rows = overview.merchantRanking,
                    rankingMetric = overview.rankingMetric,
                    onRankingMetricChange = actions.onRankingMetricChange,
                )
                if (overview.categoryComparison.isNotEmpty()) CategoryComparisonBlock(rows = overview.categoryComparison)
            }
            SettingsEntryRow(
                title = stringResource(R.string.reports_comparisons_title),
                subtitle = stringResource(R.string.reports_comparisons_description),
                icon = R.drawable.ic_lucide_calendar_check,
                onClick = { showComparisons = !showComparisons }, expanded = showComparisons,
            )
            if (showComparisons) {
                ReportsAnswerMetrics(model)
                model.trendEvidence?.takeIf { it.mode != ReportsTrendMode.Signed }?.let { ReportsTrendDetails(it) }
                ReportsRecentWindowSummary(recentTrend, avoidRepeatedSparseRows = model.trendEvidence?.mode == ReportsTrendMode.Sparse)
            }
            AppPrimaryButton(stringResource(R.string.reports_view_data), modifier = Modifier.fillMaxWidth().testTag("reports-data"),
                onClick = { showData = true })
            TextButton(onClick = { actions.onRepairRates(null) }) {
                Text(stringResource(R.string.reports_repair_rates))
            }
        }
    }
}

@Composable
private fun ReportsChartPanel(
    model: ReportsAnswerModel,
    onGranularityChange: (ReportGranularity) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight)) {
        val evidence = model.trendEvidence
        if (evidence == null) {
            Text(stringResource(R.string.reports_trend_unavailable))
        } else when (evidence.mode) {
            ReportsTrendMode.Signed -> {
                Text(stringResource(R.string.reports_signed_trend), style = MaterialTheme.typography.bodyMedium)
                StatsSparseSpendRows(model.trendPoints.filter { it.amountCents != 0L }.map {
                    StatsSpendChartPoint(label = it.label, amountCents = it.amountCents)
                }, contentDescription = trendChartA11y(model.trendPoints, LocalCurrencyDisplay.current).listed)
            }
            ReportsTrendMode.Empty -> Text(
                text = stringResource(R.string.stats_reports_chart_empty),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
            )
            ReportsTrendMode.Sparse -> ReportsSparseTrend(
                points = model.trendPoints,
                nonZeroDays = evidence.positiveBucketCount,
            )
            ReportsTrendMode.DominantPeak,
            ReportsTrendMode.Chart,
            -> ReportsTrendFlowChart(points = model.trendPoints)
        }
        AppSegmentedControl(
            options = listOf(
                AppSegmentedItem(ReportGranularity.Day, stringResource(R.string.stats_reports_granularity_day)),
                AppSegmentedItem(ReportGranularity.Week, stringResource(R.string.stats_reports_granularity_week)),
                AppSegmentedItem(ReportGranularity.Month, stringResource(R.string.reports_month_granularity)),
            ),
            selectedValue = model.granularity,
            onValueChange = onGranularityChange,
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
    if (rows.any { it.amountCents == null || it.previousAmountCents == null || it.yearOverYearAmountCents == null }) {
        Text(stringResource(R.string.reports_categories_unavailable))
        rows.forEach { row ->
            Text(stringResource(R.string.reports_category_confirmed, row.category,
                row.amountCents?.let { formatDisplayAmount(it, LocalCurrencyDisplay.current) }
                    ?: stringResource(R.string.reports_amount_unavailable), row.count))
        }
        return
    }
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
                row = row,
                maxAmountCents = maxAmount,
                showBar = chartRows.none { it.currentAmountCents < 0L } && chartRows.sumOf { it.currentAmountCents } > 0L,
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
    row: CategoryComparisonChartRow,
    maxAmountCents: Long,
    showBar: Boolean = true,
) {
    val chartTokens = LocalChartTokens.current
    val currencyDisplay = LocalCurrencyDisplay.current
    val progress = if (maxAmountCents > 0L) {
        (row.currentAmountCents.toFloat() / maxAmountCents.toFloat()).coerceIn(0f, 1f)
    } else {
        0f
    }
    val fillColor = chartTokens.series.firstOrNull() ?: MaterialTheme.colorScheme.primary
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap + AppSpacing.tinyGap)) {
        AmountBarHeader(
            label = row.category,
            amountText = formatDisplayAmount(row.currentAmountCents, currencyDisplay),
            trailingText = categoryYearOverYearText(row),
        )
        if (showBar) Box(
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
        categoryComparisonValues(row)?.let {
            Text(
                text = it,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelSmall.tabularNum(),
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
        Column(
            modifier = Modifier.fillMaxWidth(),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = label,
                style = MaterialTheme.typography.bodyMedium,
            )
            trailingText?.let {
                Text(
                    text = it,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelSmall.tabularNum(),
                )
            }
        }
    }
}

private const val ReportsCategoryAmountWeight = 0.58f

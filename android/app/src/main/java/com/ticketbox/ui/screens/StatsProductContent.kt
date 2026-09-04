package com.ticketbox.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.Dp
import com.ticketbox.R
import com.ticketbox.domain.model.LifestyleStats
import com.ticketbox.domain.model.StatsTab
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.stats.CategoryStructureCard
import com.ticketbox.ui.screens.stats.DataQualityEntryCard
import com.ticketbox.ui.screens.stats.EmptyStatsCard
import com.ticketbox.ui.screens.stats.LifestyleCard
import com.ticketbox.ui.screens.stats.ReportsInsightCard
import com.ticketbox.ui.screens.stats.StatsOverviewCard
import com.ticketbox.ui.screens.stats.StatsOverviewHeaderModel
import com.ticketbox.ui.screens.stats.StatsOverviewTrendData
import com.ticketbox.ui.screens.stats.StatsInsightSurface
import com.ticketbox.ui.screens.stats.TagScopeInsight
import com.ticketbox.ui.screens.stats.tagScopeInsightModel
import com.ticketbox.viewmodel.StatsUiState
import com.valentinilk.shimmer.shimmer

internal fun LazyListScope.statsProductItems(
    state: StatsUiState,
    selectedTab: StatsTab,
    actions: StatsReportActions,
    onOpenDataQuality: () -> Unit,
) {
    when (selectedTab.toPrimaryInsightTab()) {
        StatsTab.Overview -> statsOverviewItems(state, onOpenDataQuality)
        StatsTab.Trend -> statsTrendItems(state, actions)
        StatsTab.Category -> statsCompositionItems(state, actions)
        StatsTab.Budget,
        StatsTab.Goals,
        -> Unit
    }
}

private fun LazyListScope.statsOverviewItems(
    state: StatsUiState,
    onOpenDataQuality: () -> Unit,
) {
    val stats = state.stats ?: return
    item {
        StatsInsightSurface {
            StatsOverviewCard(
                header = StatsOverviewHeaderModel(
                    stats = stats,
                    statsSource = state.statsSource,
                    recent7DaysAmountCents = overviewRecent7DaysAmount(state),
                    comparison = overviewMonthComparison(state),
                    tagScope = tagScopeInsightModel(stats = stats, selectedTag = state.selectedTag),
                ),
                trendData = StatsOverviewTrendData(
                    reportTrend = state.reportsOverview?.trend.orEmpty(),
                ),
            )
        }
    }
    item {
        // 数据健康入口是独立可点对象：surface 给边界，行内不再带底部分隔线。
        StatsInsightSurface(
            contentPadding = PaddingValues(horizontal = AppSpacing.cardPaddingSmall),
        ) {
            DataQualityEntryCard(
                summary = state.dataQuality,
                loadState = state.dataQualityLoadState,
                onClick = onOpenDataQuality,
                showDivider = false,
            )
        }
    }
    // 标签筛选时作用域已由 hero 卡表达（同一 state.stats），不再重复第二个金额块。
    if (state.selectedTag.isBlank()) {
        state.lifestyleStats?.takeIf(LifestyleStats::hasReadableInsight)?.let { lifestyle ->
            item {
                StatsFlatSection {
                    LifestyleCard(lifestyle)
                }
            }
        }
    }
}

@Composable
private fun StatsFlatSection(
    content: @Composable () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant)
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .padding(vertical = AppSpacing.smallGap),
        ) {
            content()
        }
    }
}

private fun LazyListScope.statsTrendItems(
    state: StatsUiState,
    actions: StatsReportActions,
) {
    when {
        state.reportsOverview != null -> item {
            StatsInsightSurface {
                ReportsInsightCard(
                    overview = state.reportsOverview,
                    onGranularityChange = actions.onGranularityChange,
                    onRankingMetricChange = actions.onRankingMetricChange,
                )
            }
        }
        state.selectedTag.isNotBlank() -> item {
            state.stats?.let { stats ->
                StatsInsightSurface {
                    TagScopeInsight(
                        stats = stats,
                        selectedTag = state.selectedTag,
                        statsSource = state.statsSource,
                    )
                }
            }
        }
        state.reportsLoading -> item { StatsProductLoadingState() }
        shouldShowReportsUnavailableFallback(state) -> item {
            EmptyStatsCard(
                title = stringResource(R.string.stats_reports_unavailable_title),
                body = stringResource(R.string.stats_reports_unavailable_body),
            )
        }
    }
}

private fun LazyListScope.statsCompositionItems(
    state: StatsUiState,
    actions: StatsReportActions,
) {
    val stats = state.stats ?: return
    val categories = stats.byCategory.filter { it.amountCents > 0L && it.count > 0 }
    val tags = stats.byTag.filter { it.amountCents > 0L && it.count > 0 }
    item {
        if (categories.isEmpty()) {
            EmptyStatsCard(
                title = stringResource(
                    R.string.stats_category_empty_title,
                    displayMonthLabel(stats.month),
                ),
                body = stringResource(R.string.stats_category_empty_body),
            )
        } else {
            StatsInsightSurface {
                CategoryStructureCard(
                    categories = categories,
                    tags = tags,
                    totalAmountCents = stats.totalAmountCents,
                    onCategoryClick = actions.onDrillToLedger,
                )
            }
        }
    }
}

@Composable
internal fun StatsProductLoadingState() {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .shimmer(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        LoadingLine(height = AppSpacing.sectionGap, widthFraction = 0.44f)
        LoadingLine(height = AppSpacing.sectionGap + AppSpacing.contentGap, widthFraction = 0.72f)
        LoadingLine(height = AppSpacing.cardPaddingSmall, widthFraction = 1f)
        LoadingLine(height = AppSpacing.cardPaddingSmall, widthFraction = 0.86f)
    }
}

@Composable
private fun LoadingLine(
    height: Dp,
    widthFraction: Float,
) {
    Box(
        modifier = Modifier
            .fillMaxWidth(widthFraction)
            .height(height)
            .clip(RoundedCornerShape(AppRadius.small))
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = AppAlpha.medium)),
    )
}

private fun StatsTab.toPrimaryInsightTab(): StatsTab = when (this) {
    StatsTab.Overview,
    StatsTab.Trend,
    StatsTab.Category,
    -> this
    StatsTab.Budget,
    StatsTab.Goals,
    -> StatsTab.Overview
}

private fun LifestyleStats.hasReadableInsight(): Boolean =
    aiSubscriptionAmountCents > 0L ||
        digitalAmountCents > 0L ||
        maxExpense != null ||
        frequentMerchants.isNotEmpty() ||
        bestValueExpenses.isNotEmpty() ||
        mostRegrettedExpenses.isNotEmpty()

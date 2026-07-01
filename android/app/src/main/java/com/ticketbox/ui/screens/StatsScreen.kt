package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.DASHBOARD_CARD_BUDGET
import com.ticketbox.domain.model.DASHBOARD_CARD_GOALS
import com.ticketbox.domain.model.DASHBOARD_CARD_MONTHLY_SPEND
import com.ticketbox.domain.model.DASHBOARD_CARD_PENDING
import com.ticketbox.domain.model.DASHBOARD_CARD_RECENT_UPLOADS
import com.ticketbox.domain.model.DASHBOARD_CARD_RECURRING
import com.ticketbox.domain.model.DASHBOARD_CARD_REPORTS
import com.ticketbox.domain.model.DashboardCard
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.StatsTab
import com.ticketbox.domain.model.statsDashboardKeysForTab
import com.ticketbox.domain.model.visibleDashboardCardKeys
import com.ticketbox.ui.components.AppErrorState
import com.ticketbox.ui.components.CardSkeleton
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.components.MonthPickerSheet
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.screens.stats.CategoryStructureCard
import com.ticketbox.ui.screens.stats.EmptyStatsCard
import com.ticketbox.ui.screens.stats.LifestyleCard
import com.ticketbox.ui.screens.stats.PendingOverviewCard
import com.ticketbox.ui.screens.stats.RecentTrendCard
import com.ticketbox.ui.screens.stats.RecentUploadCard
import com.ticketbox.ui.screens.stats.RecurringCandidatesCard
import com.ticketbox.ui.screens.stats.RecurringItemsSummaryCard
import com.ticketbox.ui.screens.stats.GoalsSummaryCard
import com.ticketbox.ui.screens.stats.ReportsInsightCard
import com.ticketbox.ui.screens.stats.StatsMetricGrid
import com.ticketbox.ui.screens.stats.StatsOverviewCard
import com.ticketbox.ui.screens.stats.StatsOverviewTrendData
import com.ticketbox.ui.screens.stats.StatsLeadInsight
import com.ticketbox.ui.screens.stats.StatsPlanningActions
import com.ticketbox.ui.screens.stats.StatsTopPanel
import com.ticketbox.ui.screens.stats.StatsTopPanelActions
import com.ticketbox.ui.asString
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.StatsSource
import com.ticketbox.viewmodel.StatsUiState
import com.valentinilk.shimmer.shimmer

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StatsScreen(
    state: StatsUiState,
    onMonthChange: (String) -> Unit,
    onTagChange: (String) -> Unit,
    onRefresh: () -> Unit,
    onOpenBudget: () -> Unit,
    onOpenRecurring: () -> Unit,
    onOpenIncomePlans: () -> Unit = {},
    // ADR-0049 §6 (slice 7): 还债目标二级页。默认 no-op 保旧调用方/预览。
    onOpenDebtGoals: () -> Unit = {},
    // §三报表钻取:分类行点击 → 账本带(当前统计月, 分类)筛选打开。默认 no-op 保旧调用方。
    onDrillToLedger: (String) -> Unit = {},
    // 轴3 粒度切换:动态图表卡的日/周档切换,交给 StatsReportsViewModel 重拉。
    onGranularityChange: (ReportGranularity) -> Unit = {},
) {
    var showMonthPicker by rememberSaveable { mutableStateOf(false) }
    var selectedStatsTab by rememberSaveable { mutableStateOf(StatsTab.Overview) }

    if (showMonthPicker) {
        ModalBottomSheet(onDismissRequest = { showMonthPicker = false }) {
            MonthPickerSheet(
                months = state.months,
                selectedMonth = state.month,
                description = stringResource(R.string.stats_month_picker_description),
                onSelectMonth = { month ->
                    onMonthChange(month)
                    showMonthPicker = false
                },
            )
        }
    }

    AppScrollableContent(
        role = AppPageRole.Stats,
        isRefreshing = state.loading,
        onRefresh = onRefresh,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        val visibleDashboardKeys = orderedStatsDashboardKeys(visibleDashboardCardKeys(state.dashboardCards))
        val tagFilterActive = state.selectedTag.isNotBlank()
        val selectedDashboardKeys = orderedStatsDashboardKeys(
            statsDashboardKeysForTab(
                selectedStatsTab,
                visibleDashboardKeys,
                tagFilterActive = tagFilterActive,
            ),
        )
        val authorityTone = when {
            state.loading -> DataAuthorityTone.Refreshing
            state.statsSource == StatsSource.LocalFallback -> DataAuthorityTone.LocalCache
            state.statsSource == StatsSource.Backend -> DataAuthorityTone.Backend
            else -> null
        }
        item {
            StatsTopPanel(
                state = state,
                selectedTab = selectedStatsTab,
                visibleDashboardKeys = visibleDashboardKeys,
                actions = StatsTopPanelActions(
                    onOpenMonthPicker = { showMonthPicker = true },
                    onTagChange = { tag ->
                        onTagChange(tag)
                        if (tag.isNotBlank() && selectedStatsTab in tagScopedHiddenTabs) {
                            selectedStatsTab = StatsTab.Trend
                        }
                    },
                    onTabChange = { selectedStatsTab = it },
                    planning = StatsPlanningActions(
                        onOpenBudget = onOpenBudget,
                        onOpenRecurring = onOpenRecurring,
                        onOpenIncomePlans = onOpenIncomePlans,
                        onOpenDebtGoals = onOpenDebtGoals,
                    ),
                ),
            )
        }
        authorityTone?.takeIf { it != DataAuthorityTone.Backend }?.let { tone ->
            item {
                AppDataAuthorityStrip(
                    tone = tone,
                )
            }
        }
        state.message?.let {
            item { Text(it.asString(), color = MaterialTheme.colorScheme.secondary) }
        }
        state.reportsMessage?.let {
            item { Text(it.asString(), color = MaterialTheme.colorScheme.secondary) }
        }
        state.dashboardCardsMessage?.let {
            item { Text(it.asString(), color = MaterialTheme.colorScheme.secondary) }
        }
        val stats = state.stats
        if (stats == null) {
            item {
                when {
                    state.loading -> Column(
                        modifier = Modifier.shimmer(),
                        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
                    ) {
                        repeat(4) { CardSkeleton(lines = 3) }
                    }
                    // A failed load with no data → retryable error state, not the empty
                    // card that reads like "没有数据" (审计 8.4).
                    state.statsLoadError != null -> AppErrorState(
                        title = stringResource(R.string.stats_error_card_title),
                        body = state.statsLoadError.asString().ifBlank {
                            stringResource(R.string.stats_error_card_body)
                        },
                        onRetry = onRefresh,
                    )
                    else -> EmptyStatsCard(onRefresh = onRefresh)
                }
            }
            return@AppScrollableContent
        }
        val visibleCategories = stats.byCategory.filter { it.amountCents > 0L && it.count > 0 }
        val visibleTags = stats.byTag.filter { it.amountCents > 0L && it.count > 0 }
        val recentUploadMergedIntoOverview = selectedStatsTab == StatsTab.Overview &&
            DASHBOARD_CARD_MONTHLY_SPEND in selectedDashboardKeys &&
            DASHBOARD_CARD_RECENT_UPLOADS in selectedDashboardKeys
        var renderedCard = false

        val showLeadInsight = selectedStatsTab == StatsTab.Overview &&
            DASHBOARD_CARD_MONTHLY_SPEND in selectedDashboardKeys

        if (showLeadInsight) {
            renderedCard = true
            item { StatsLeadInsight(state) }
        }

        selectedDashboardKeys.forEach { key ->
            when (key) {
                DASHBOARD_CARD_MONTHLY_SPEND -> {
                    if (!showLeadInsight) {
                        renderedCard = true
                        item {
                            StatsOverviewCard(
                                stats = stats,
                                statsSource = state.statsSource,
                                recent7DaysAmountCents = overviewRecent7DaysAmount(state),
                                comparison = state.monthComparison,
                                trendData = StatsOverviewTrendData(
                                    dailyTrend = if (
                                        state.statsSource == StatsSource.LocalFallback &&
                                        state.reportsOverview == null
                                    ) {
                                        state.dailyTrend
                                    } else {
                                        emptyList()
                                    },
                                    reportTrend = state.reportsOverview?.trend.orEmpty(),
                                    includeRecentUpload = recentUploadMergedIntoOverview,
                                    lastUploadAt = state.lastUploadAt,
                                ),
                            )
                        }
                    }
                }

                DASHBOARD_CARD_BUDGET -> {
                    renderedCard = true
                    item {
                        StatsMetricGrid(
                            budget = state.budgetProgress,
                            onOpenBudget = onOpenBudget,
                        )
                    }
                }

                DASHBOARD_CARD_REPORTS -> {
                    renderedCard = true
                    if (selectedStatsTab == StatsTab.Category) {
                        if (visibleCategories.isEmpty()) {
                            item {
                                EmptyStatsCard(
                                    title = stringResource(R.string.stats_category_empty_title, displayMonthLabel(stats.month)),
                                    body = stringResource(R.string.stats_category_empty_body),
                                )
                            }
                        } else {
                            item {
                                CategoryStructureCard(
                                    categories = visibleCategories,
                                    tags = visibleTags,
                                    totalAmountCents = stats.totalAmountCents,
                                    onCategoryClick = onDrillToLedger,
                                )
                            }
                        }
                    }
                    if (selectedStatsTab == StatsTab.Trend) {
                        if (state.selectedTag.isBlank()) {
                            val overview = state.reportsOverview
                            if (overview != null) {
                                item {
                                    ReportsInsightCard(
                                        overview = overview,
                                        recentTrend = state.dailyTrend,
                                        onGranularityChange = onGranularityChange,
                                    )
                                }
                            } else {
                                item { RecentTrendCard(state.dailyTrend) }
                            }
                        } else {
                            item { RecentTrendCard(state.dailyTrend) }
                        }
                    }
                }

                DASHBOARD_CARD_GOALS -> {
                    if (state.selectedTag.isBlank()) {
                        renderedCard = true
                        item { GoalsSummaryCard(state.reportGoals) }
                    }
                }

                DASHBOARD_CARD_RECURRING -> {
                    if (state.recurringItems.isNotEmpty()) {
                        renderedCard = true
                        item { RecurringItemsSummaryCard(state.recurringItems) }
                    }
                    if (state.recurringCandidates.isNotEmpty()) {
                        renderedCard = true
                        item { RecurringCandidatesCard(state.recurringCandidates) }
                    }
                }

                DASHBOARD_CARD_PENDING -> {
                    state.dataQuality?.let { dq ->
                        renderedCard = true
                        item { PendingOverviewCard(dq) }
                    }
                }

                DASHBOARD_CARD_RECENT_UPLOADS -> {
                    if (!recentUploadMergedIntoOverview) {
                        renderedCard = true
                        item { RecentUploadCard(state.lastUploadAt) }
                    }
                    state.lifestyleStats?.let { lifestyle ->
                        renderedCard = true
                        item { LifestyleCard(lifestyle) }
                    }
                }
            }
        }

        if (!renderedCard) {
            item {
                EmptyStatsCard(
                    title = stringResource(R.string.stats_all_cards_hidden_title),
                    body = stringResource(R.string.stats_all_cards_hidden_body),
                )
            }
        }
    }
}

private fun orderedStatsDashboardKeys(keys: List<String>): List<String> {
    val preferredOrder = listOf(
        DASHBOARD_CARD_MONTHLY_SPEND,
        DASHBOARD_CARD_BUDGET,
        DASHBOARD_CARD_REPORTS,
        DASHBOARD_CARD_GOALS,
        DASHBOARD_CARD_RECURRING,
        DASHBOARD_CARD_PENDING,
        DASHBOARD_CARD_RECENT_UPLOADS,
    )
    return preferredOrder.filter { it in keys } + keys.filter { it !in preferredOrder }
}

private fun overviewRecent7DaysAmount(state: StatsUiState): Long? {
    if (state.statsSource == StatsSource.LocalFallback) {
        return state.dailyTrend.sumOf { it.amountCents.coerceAtLeast(0L) }
    }
    return state.lifestyleStats?.recent7DaysAmountCents
}

private val tagScopedHiddenTabs = setOf(StatsTab.Budget, StatsTab.Goals)

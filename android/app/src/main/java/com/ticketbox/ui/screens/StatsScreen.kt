package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
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
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.CardSkeleton
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.AppSegmentedControl
import com.ticketbox.ui.components.AppSegmentedItem
import com.ticketbox.ui.components.MonthPickerSheet
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.screens.stats.CategoryStructureCard
import com.ticketbox.ui.screens.stats.EmptyStatsCard
import com.ticketbox.ui.screens.stats.FrequentMerchantsCard
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
import com.ticketbox.ui.screens.stats.TagStatsCard
import com.ticketbox.ui.asString
import com.ticketbox.ui.design.AppSpacing
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
        val selectedDashboardKeys = orderedStatsDashboardKeys(
            statsDashboardKeysForTab(selectedStatsTab, visibleDashboardKeys),
        )
        item {
            StatsTopPanel(
                state = state,
                selectedTab = selectedStatsTab,
                visibleDashboardKeys = visibleDashboardKeys,
                onOpenMonthPicker = { showMonthPicker = true },
                onTagChange = onTagChange,
                onTabChange = { selectedStatsTab = it },
                onOpenBudget = onOpenBudget,
                onOpenRecurring = onOpenRecurring,
            )
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
        var renderedCard = false

        selectedDashboardKeys.forEach { key ->
            when (key) {
                DASHBOARD_CARD_MONTHLY_SPEND -> {
                    renderedCard = true
                    item {
                        StatsOverviewCard(
                            stats = stats,
                            statsSource = state.statsSource,
                            recent7DaysAmountCents = if (state.selectedTag.isBlank()) {
                                state.lifestyleStats?.recent7DaysAmountCents
                                    ?: state.dailyTrend.sumOf { it.amountCents }
                            } else {
                                state.dailyTrend.sumOf { it.amountCents }
                            },
                            comparison = state.monthComparison,
                            dailyTrend = state.dailyTrend,
                        )
                    }
                }

                DASHBOARD_CARD_BUDGET -> {
                    renderedCard = true
                    item {
                        StatsMetricGrid(
                            stats = stats,
                            lifestyle = state.lifestyleStats,
                            insight = state.categoryInsight,
                            budget = state.budgetProgress,
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
                                    totalAmountCents = stats.totalAmountCents,
                                    insight = state.categoryInsight,
                                    onCategoryClick = onDrillToLedger,
                                )
                            }
                        }
                        if (visibleTags.isNotEmpty()) {
                            item {
                                TagStatsCard(
                                    tags = visibleTags,
                                    totalAmountCents = stats.totalAmountCents,
                                )
                            }
                        }
                    }
                    if (selectedStatsTab == StatsTab.Trend) {
                        item { RecentTrendCard(state.dailyTrend) }
                        if (state.selectedTag.isBlank()) {
                            state.reportsOverview?.let { overview ->
                                item {
                                    ReportsInsightCard(
                                        overview = overview,
                                        onGranularityChange = onGranularityChange,
                                    )
                                }
                            }
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
                    renderedCard = true
                    item { RecentUploadCard(state.lastUploadAt) }
                    state.lifestyleStats?.let { lifestyle ->
                        item { LifestyleCard(lifestyle) }
                        if (lifestyle.frequentMerchants.isNotEmpty()) {
                            item { FrequentMerchantsCard(lifestyle.frequentMerchants) }
                        }
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

@Composable
private fun StatsTopPanel(
    state: StatsUiState,
    selectedTab: StatsTab,
    visibleDashboardKeys: List<String>,
    onOpenMonthPicker: () -> Unit,
    onTagChange: (String) -> Unit,
    onTabChange: (StatsTab) -> Unit,
    onOpenBudget: () -> Unit,
    onOpenRecurring: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactPadding)) {
        AppPageHeader(
            title = stringResource(R.string.stats_header_title),
            action = {
                TextButton(onClick = onOpenBudget) {
                    Text(text = stringResource(R.string.stats_header_open_budget), style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold)
                }
                TextButton(onClick = onOpenRecurring) {
                    Text(text = stringResource(R.string.stats_header_open_recurring), style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold)
                }
            },
        )
        StatsFilterRow(
            state = state,
            onOpenMonthPicker = onOpenMonthPicker,
            onTagChange = onTagChange,
        )
        StatsTabRow(
            selectedTab = selectedTab,
            dashboardCards = state.dashboardCards,
            visibleDashboardKeys = visibleDashboardKeys,
            onTabChange = onTabChange,
        )
    }
}

@Composable
private fun StatsTabRow(
    selectedTab: StatsTab,
    dashboardCards: List<DashboardCard>,
    visibleDashboardKeys: List<String>,
    onTabChange: (StatsTab) -> Unit,
) {
    AppSegmentedControl(
        options = StatsTab.entries.map { tab ->
            AppSegmentedItem(
                value = tab,
                label = statsTabLabel(tab, dashboardCards),
                enabled = statsDashboardKeysForTab(tab, visibleDashboardKeys).isNotEmpty(),
            )
        },
        selectedValue = selectedTab,
        onValueChange = onTabChange,
    )
}

@Composable
private fun statsTabLabel(
    tab: StatsTab,
    dashboardCards: List<DashboardCard>,
): String {
    val titleByKey = dashboardCards
        .filter { it.title.isNotBlank() }
        .associate { it.key to it.title }
    return when (tab) {
        StatsTab.Overview -> titleByKey[DASHBOARD_CARD_MONTHLY_SPEND] ?: stringResource(R.string.stats_tab_overview)
        StatsTab.Trend -> titleByKey[DASHBOARD_CARD_REPORTS] ?: stringResource(R.string.stats_tab_trend)
        StatsTab.Category -> stringResource(R.string.stats_tab_category)
        StatsTab.Budget -> titleByKey[DASHBOARD_CARD_BUDGET] ?: stringResource(R.string.stats_tab_budget)
        StatsTab.Goals -> titleByKey[DASHBOARD_CARD_GOALS] ?: stringResource(R.string.stats_tab_goals)
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

@Composable
private fun StatsFilterRow(
    state: StatsUiState,
    onOpenMonthPicker: () -> Unit,
    onTagChange: (String) -> Unit,
) {
    val tags = (state.tags + state.stats?.byTag.orEmpty().map { it.tag })
        .map { it.trim() }
        .filter { it.isNotBlank() }
        .distinctBy { it.lowercase() }
        .let { items ->
            if (state.selectedTag.isBlank() || items.any { it.equals(state.selectedTag, ignoreCase = true) }) {
                items
            } else {
                listOf(state.selectedTag) + items
            }
        }
        .take(12)
    LazyRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
        item {
            AppFilterChip(
                selected = true,
                onClick = onOpenMonthPicker,
                label = state.month.takeIf { it.isNotBlank() }?.let(::displayMonthLabel)
                    ?: stringResource(R.string.stats_filter_all_months),
                trailingIcon = { FilterTrailingIcon(Icons.Filled.ExpandMore, stringResource(R.string.stats_filter_pick_month_description)) },
            )
        }
        item {
            AppFilterChip(
                selected = state.selectedTag.isBlank(),
                onClick = { onTagChange("") },
                label = stringResource(R.string.stats_filter_all_tags),
            )
        }
        items(tags, key = { it }) { tag ->
            val selected = state.selectedTag.equals(tag, ignoreCase = true)
            AppFilterChip(
                selected = selected,
                onClick = { onTagChange(if (selected) "" else tag) },
                label = "#$tag",
                trailingIcon = if (selected) {
                    { FilterTrailingIcon(Icons.Filled.Close, stringResource(R.string.stats_filter_clear_tag_description)) }
                } else {
                    null
                },
            )
        }
    }
}

@Composable
private fun FilterTrailingIcon(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    contentDescription: String,
) {
    Icon(
        imageVector = icon,
        contentDescription = contentDescription,
        modifier = Modifier.size(16.dp),
    )
}

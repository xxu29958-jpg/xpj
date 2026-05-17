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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.DASHBOARD_CARD_BUDGET
import com.ticketbox.domain.model.DASHBOARD_CARD_GOALS
import com.ticketbox.domain.model.DASHBOARD_CARD_MONTHLY_SPEND
import com.ticketbox.domain.model.DASHBOARD_CARD_PENDING
import com.ticketbox.domain.model.DASHBOARD_CARD_RECENT_UPLOADS
import com.ticketbox.domain.model.DASHBOARD_CARD_RECURRING
import com.ticketbox.domain.model.DASHBOARD_CARD_REPORTS
import com.ticketbox.domain.model.DashboardCard
import com.ticketbox.domain.model.StatsTab
import com.ticketbox.domain.model.statsDashboardKeysForTab
import com.ticketbox.domain.model.visibleDashboardCardKeys
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
) {
    var showMonthPicker by rememberSaveable { mutableStateOf(false) }
    var selectedStatsTab by rememberSaveable { mutableStateOf(StatsTab.Overview) }

    if (showMonthPicker) {
        ModalBottomSheet(onDismissRequest = { showMonthPicker = false }) {
            MonthPickerSheet(
                months = state.months,
                selectedMonth = state.month,
                description = "选择后刷新统计。本页按消费时间统计，没有消费时间时按确认时间。",
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
            item { Text(it, color = MaterialTheme.colorScheme.secondary) }
        }
        state.reportsMessage?.let {
            item { Text(it, color = MaterialTheme.colorScheme.secondary) }
        }
        state.dashboardCardsMessage?.let {
            item { Text(it, color = MaterialTheme.colorScheme.secondary) }
        }
        val stats = state.stats
        if (stats == null) {
            item {
                if (state.loading) {
                    Column(
                        modifier = Modifier.shimmer(),
                        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
                    ) {
                        repeat(4) { CardSkeleton(lines = 3) }
                    }
                } else {
                    EmptyStatsCard(onRefresh = onRefresh)
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
                                    title = "${displayMonthLabel(stats.month)} 暂无分类支出",
                                    body = "确认几笔账单后，这里会显示分类占比。",
                                )
                            }
                        } else {
                            item {
                                CategoryStructureCard(
                                    categories = visibleCategories,
                                    totalAmountCents = stats.totalAmountCents,
                                    insight = state.categoryInsight,
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
                                item { ReportsInsightCard(overview) }
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
                    title = "首页卡片已全部隐藏",
                    body = "可以在设置 > 首页卡片中恢复默认卡片。",
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
            title = "统计",
            action = {
                TextButton(onClick = onOpenBudget) {
                    Text(text = "预算 →", style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold)
                }
                TextButton(onClick = onOpenRecurring) {
                    Text(text = "固定支出 →", style = MaterialTheme.typography.labelLarge, fontWeight = FontWeight.SemiBold)
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

private fun statsTabLabel(
    tab: StatsTab,
    dashboardCards: List<DashboardCard>,
): String {
    val titleByKey = dashboardCards
        .filter { it.title.isNotBlank() }
        .associate { it.key to it.title }
    return when (tab) {
        StatsTab.Overview -> titleByKey[DASHBOARD_CARD_MONTHLY_SPEND] ?: "概览"
        StatsTab.Trend -> titleByKey[DASHBOARD_CARD_REPORTS] ?: "趋势"
        StatsTab.Category -> "分类"
        StatsTab.Budget -> titleByKey[DASHBOARD_CARD_BUDGET] ?: "预算"
        StatsTab.Goals -> titleByKey[DASHBOARD_CARD_GOALS] ?: "目标"
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
                label = state.month.takeIf { it.isNotBlank() }?.let(::displayMonthLabel) ?: "全部月份",
                trailingIcon = { FilterTrailingIcon(Icons.Filled.ExpandMore, "选择月份") },
            )
        }
        item {
            AppFilterChip(
                selected = state.selectedTag.isBlank(),
                onClick = { onTagChange("") },
                label = "全部标签",
            )
        }
        items(tags, key = { it }) { tag ->
            val selected = state.selectedTag.equals(tag, ignoreCase = true)
            AppFilterChip(
                selected = selected,
                onClick = { onTagChange(if (selected) "" else tag) },
                label = "#$tag",
                trailingIcon = if (selected) {
                    { FilterTrailingIcon(Icons.Filled.Close, "清除标签筛选") }
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

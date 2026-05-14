package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.clickable
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AccountBalanceWallet
import androidx.compose.material.icons.filled.Category
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.DASHBOARD_CARD_BUDGET
import com.ticketbox.domain.model.DASHBOARD_CARD_GOALS
import com.ticketbox.domain.model.DASHBOARD_CARD_MONTHLY_SPEND
import com.ticketbox.domain.model.DASHBOARD_CARD_PENDING
import com.ticketbox.domain.model.DASHBOARD_CARD_RECENT_UPLOADS
import com.ticketbox.domain.model.DASHBOARD_CARD_RECURRING
import com.ticketbox.domain.model.DASHBOARD_CARD_REPORTS
import com.ticketbox.domain.model.visibleDashboardCardKeys
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.MonthPickerSheet
import com.ticketbox.ui.components.SafeBadge
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
import com.ticketbox.ui.screens.stats.StatsMonthChip
import com.ticketbox.ui.screens.stats.StatsOverviewCard
import com.ticketbox.ui.screens.stats.TagStatsCard
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.viewmodel.StatsUiState

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
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                AppPageHeader(
                    title = "统计",
                    subtitle = "生活消费感知",
                ) {
                    SafeBadge()
                }
                StatsMonthChip(
                    selectedMonth = state.month,
                    onClick = { showMonthPicker = true },
                )
                StatsTagFilterRow(
                    state = state,
                    onTagChange = onTagChange,
                )
            }
        }
        item {
            StatsSecondaryEntryRow(
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
            item { EmptyStatsCard(onRefresh = onRefresh) }
        } else {
            val visibleDashboardKeys = orderedStatsDashboardKeys(visibleDashboardCardKeys(state.dashboardCards))
            val visibleCategories = stats.byCategory.filter { it.amountCents > 0L && it.count > 0 }
            val visibleTags = stats.byTag.filter { it.amountCents > 0L && it.count > 0 }
            var renderedCard = false

            visibleDashboardKeys.forEach { key ->
                when (key) {
                    DASHBOARD_CARD_PENDING -> {
                        state.dataQuality?.let { dq ->
                            renderedCard = true
                            item {
                                PendingOverviewCard(dq)
                            }
                        }
                    }

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
                            )
                        }
                    }

                    DASHBOARD_CARD_REPORTS -> {
                        renderedCard = true
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
                        item {
                            RecentTrendCard(state.dailyTrend)
                        }
                        if (state.selectedTag.isBlank()) {
                            state.reportsOverview?.let { overview ->
                                item {
                                    ReportsInsightCard(overview)
                                }
                            }
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

                    DASHBOARD_CARD_GOALS -> {
                        if (state.selectedTag.isBlank()) {
                            renderedCard = true
                            item {
                                GoalsSummaryCard(state.reportGoals)
                            }
                        }
                    }

                    DASHBOARD_CARD_RECURRING -> {
                        if (state.recurringItems.isNotEmpty()) {
                            renderedCard = true
                            item {
                                RecurringItemsSummaryCard(state.recurringItems)
                            }
                        }
                        if (state.recurringCandidates.isNotEmpty()) {
                            renderedCard = true
                            item {
                                RecurringCandidatesCard(state.recurringCandidates)
                            }
                        }
                    }

                    DASHBOARD_CARD_RECENT_UPLOADS -> {
                        renderedCard = true
                        item {
                            RecentUploadCard(state.lastUploadAt)
                        }
                        state.lifestyleStats?.let { lifestyle ->
                            item {
                                LifestyleCard(lifestyle)
                            }
                            if (lifestyle.frequentMerchants.isNotEmpty()) {
                                item {
                                    FrequentMerchantsCard(lifestyle.frequentMerchants)
                                }
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
}

private fun orderedStatsDashboardKeys(keys: List<String>): List<String> {
    val preferredOrder = listOf(
        DASHBOARD_CARD_MONTHLY_SPEND,
        DASHBOARD_CARD_REPORTS,
        DASHBOARD_CARD_BUDGET,
        DASHBOARD_CARD_PENDING,
        DASHBOARD_CARD_GOALS,
        DASHBOARD_CARD_RECURRING,
        DASHBOARD_CARD_RECENT_UPLOADS,
    )
    return preferredOrder.filter { it in keys } + keys.filter { it !in preferredOrder }
}

@Composable
private fun StatsSecondaryEntryRow(
    onOpenBudget: () -> Unit,
    onOpenRecurring: () -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        StatsSecondaryEntryCard(
            title = "预算",
            subtitle = "月度可花额度",
            icon = Icons.Filled.AccountBalanceWallet,
            onClick = onOpenBudget,
            modifier = Modifier.weight(1f),
        )
        StatsSecondaryEntryCard(
            title = "固定支出",
            subtitle = "周期账单提醒",
            icon = Icons.Filled.Category,
            onClick = onOpenRecurring,
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
private fun StatsSecondaryEntryCard(
    title: String,
    subtitle: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val visuals = LocalThemeVisuals.current
    AppGlassCard(
        modifier = modifier.clickable(onClick = onClick),
        containerAlpha = 0.96f,
    ) {
        Row(
            modifier = Modifier.padding(14.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalAlignment = androidx.compose.ui.Alignment.CenterVertically,
        ) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = visuals.primary,
                modifier = Modifier.size(22.dp),
            )
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(
                    text = title,
                    style = MaterialTheme.typography.titleSmall,
                    fontWeight = androidx.compose.ui.text.font.FontWeight.Black,
                    maxLines = 1,
                    overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                )
                Text(
                    text = subtitle,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.labelSmall,
                    maxLines = 1,
                    overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
                )
            }
        }
    }
}

@Composable
private fun StatsTagFilterRow(
    state: StatsUiState,
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
    if (tags.isEmpty() && state.selectedTag.isBlank()) {
        return
    }

    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
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
                    {
                        Icon(
                            imageVector = Icons.Filled.Close,
                            contentDescription = "清除标签筛选",
                            modifier = Modifier.size(FilterChipDefaults.IconSize),
                        )
                    }
                } else {
                    null
                },
            )
        }
    }
}

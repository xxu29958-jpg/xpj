package com.ticketbox.ui.screens

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ExpandLess
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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.DASHBOARD_CARD_BUDGET
import com.ticketbox.domain.model.DASHBOARD_CARD_GOALS
import com.ticketbox.domain.model.DASHBOARD_CARD_MONTHLY_SPEND
import com.ticketbox.domain.model.DASHBOARD_CARD_PENDING
import com.ticketbox.domain.model.DASHBOARD_CARD_RECENT_UPLOADS
import com.ticketbox.domain.model.DASHBOARD_CARD_RECURRING
import com.ticketbox.domain.model.DASHBOARD_CARD_REPORTS
import com.ticketbox.domain.model.visibleDashboardCardKeys
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.CardSkeleton
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.MonthPickerSheet
import com.ticketbox.ui.components.SectionTitle
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

    var maintenanceExpanded by rememberSaveable { mutableStateOf(false) }

    AppScrollableContent(
        role = AppPageRole.Stats,
        isRefreshing = state.loading,
        onRefresh = onRefresh,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        val visibleDashboardKeys = orderedStatsDashboardKeys(visibleDashboardCardKeys(state.dashboardCards))
        item {
            StatsTopPanel(
                state = state,
                onOpenMonthPicker = { showMonthPicker = true },
                onTagChange = onTagChange,
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
        var lastSection: String? = null

        visibleDashboardKeys.forEach { key ->
            val section = STATS_SECTION_FOR[key]
            val isMaintenance = section == STATS_SECTION_MAINTENANCE
            if (section != null && section != lastSection) {
                if (isMaintenance) {
                    item(key = "section_$section") {
                        MaintenanceSectionHeader(
                            expanded = maintenanceExpanded,
                            onToggle = { maintenanceExpanded = !maintenanceExpanded },
                        )
                    }
                } else {
                    item(key = "section_$section") {
                        SectionTitle(
                            title = section,
                            modifier = Modifier.padding(top = AppSpacing.compactGap),
                        )
                    }
                }
                lastSection = section
            }
            // 维护区折叠时只显示 section 头，不渲染任何卡片。
            if (isMaintenance && !maintenanceExpanded) return@forEach

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
                    item { RecentTrendCard(state.dailyTrend) }
                    if (state.selectedTag.isBlank()) {
                        state.reportsOverview?.let { overview ->
                            item { ReportsInsightCard(overview) }
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

private const val STATS_SECTION_OVERVIEW = "本月概览"
private const val STATS_SECTION_TRENDS = "结构与趋势"
private const val STATS_SECTION_PLAN = "计划与提醒"
private const val STATS_SECTION_MAINTENANCE = "记账维护"

private val STATS_SECTION_FOR: Map<String, String> = mapOf(
    DASHBOARD_CARD_MONTHLY_SPEND to STATS_SECTION_OVERVIEW,
    DASHBOARD_CARD_BUDGET to STATS_SECTION_OVERVIEW,
    DASHBOARD_CARD_REPORTS to STATS_SECTION_TRENDS,
    DASHBOARD_CARD_GOALS to STATS_SECTION_PLAN,
    DASHBOARD_CARD_RECURRING to STATS_SECTION_PLAN,
    DASHBOARD_CARD_PENDING to STATS_SECTION_MAINTENANCE,
    DASHBOARD_CARD_RECENT_UPLOADS to STATS_SECTION_MAINTENANCE,
)

@Composable
private fun MaintenanceSectionHeader(
    expanded: Boolean,
    onToggle: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(top = AppSpacing.compactGap)
            .clickable(role = Role.Button, onClick = onToggle),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        SectionTitle(
            title = STATS_SECTION_MAINTENANCE,
            modifier = Modifier.weight(1f),
        )
        Icon(
            imageVector = if (expanded) Icons.Filled.ExpandLess else Icons.Filled.ExpandMore,
            contentDescription = if (expanded) "收起记账维护" else "展开记账维护",
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(20.dp),
        )
    }
}

@Composable
private fun StatsTopPanel(
    state: StatsUiState,
    onOpenMonthPicker: () -> Unit,
    onTagChange: (String) -> Unit,
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

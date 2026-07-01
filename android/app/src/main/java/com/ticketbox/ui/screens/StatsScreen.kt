package com.ticketbox.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.clickable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.clearAndSetSemantics
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.onClick
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.stateDescription
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
import com.ticketbox.ui.asString
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStatsTokens
import com.ticketbox.ui.design.LocalThemeVisuals
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
        val selectedDashboardKeys = orderedStatsDashboardKeys(
            statsDashboardKeysForTab(selectedStatsTab, visibleDashboardKeys),
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
                onOpenMonthPicker = { showMonthPicker = true },
                onTagChange = onTagChange,
                onTabChange = { selectedStatsTab = it },
                onOpenBudget = onOpenBudget,
                onOpenRecurring = onOpenRecurring,
                onOpenIncomePlans = onOpenIncomePlans,
                onOpenDebtGoals = onOpenDebtGoals,
            )
        }
        authorityTone?.let { tone ->
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

        selectedDashboardKeys.forEach { key ->
            when (key) {
                DASHBOARD_CARD_MONTHLY_SPEND -> {
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
    onOpenIncomePlans: () -> Unit,
    onOpenDebtGoals: () -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
        AppPageHeader(
            title = stringResource(R.string.stats_header_title),
            action = {
                StatsPlanningMenu(
                    onOpenBudget = onOpenBudget,
                    onOpenRecurring = onOpenRecurring,
                    onOpenIncomePlans = onOpenIncomePlans,
                    onOpenDebtGoals = onOpenDebtGoals,
                )
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
private fun StatsPlanningMenu(
    onOpenBudget: () -> Unit,
    onOpenRecurring: () -> Unit,
    onOpenIncomePlans: () -> Unit,
    onOpenDebtGoals: () -> Unit,
) {
    var menuOpen by remember { mutableStateOf(false) }
    Box {
        StatsPlanningMenuTrigger(
            expanded = menuOpen,
            onOpen = { menuOpen = true },
        )
        DropdownMenu(expanded = menuOpen, onDismissRequest = { menuOpen = false }) {
            DropdownMenuItem(
                text = { Text(stringResource(R.string.stats_header_open_budget)) },
                onClick = { menuOpen = false; onOpenBudget() },
            )
            DropdownMenuItem(
                text = { Text(stringResource(R.string.stats_header_open_recurring)) },
                onClick = { menuOpen = false; onOpenRecurring() },
            )
            DropdownMenuItem(
                text = { Text(stringResource(R.string.stats_header_open_income_plans)) },
                onClick = { menuOpen = false; onOpenIncomePlans() },
            )
            DropdownMenuItem(
                text = { Text(stringResource(R.string.stats_header_open_debt_goals)) },
                onClick = { menuOpen = false; onOpenDebtGoals() },
            )
        }
    }
}

@Composable
private fun StatsPlanningMenuTrigger(
    expanded: Boolean,
    onOpen: () -> Unit,
) {
    val visuals = LocalThemeVisuals.current
    val controlTokens = LocalStatsTokens.current.control
    val menuDescription = stringResource(R.string.stats_header_menu_planning_description)
    val menuStateDescription = stringResource(
        if (expanded) {
            R.string.stats_header_menu_planning_expanded
        } else {
            R.string.stats_header_menu_planning_collapsed
        },
    )
    Row(
        modifier = Modifier
            .clearAndSetSemantics {
                contentDescription = menuDescription
                stateDescription = menuStateDescription
                role = Role.Button
                onClick(action = {
                    onOpen()
                    true
                })
            }
            .height(controlTokens.height)
            .widthIn(min = 48.dp)
            .clip(RoundedCornerShape(AppRadius.pill))
            .background(visuals.chipSelected.copy(alpha = controlTokens.selectedAlpha))
            .border(
                width = 1.dp,
                color = MaterialTheme.colorScheme.primary.copy(alpha = controlTokens.borderAlpha),
                shape = RoundedCornerShape(AppRadius.pill),
            )
            .clickable(role = Role.Button, onClick = onOpen)
            .padding(horizontal = controlTokens.horizontalPadding),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = stringResource(R.string.stats_header_menu_planning),
            color = MaterialTheme.colorScheme.primary,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = FontWeight.SemiBold,
        )
        Icon(
            imageVector = Icons.Default.ArrowDropDown,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
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
    LazyRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.chipGap)) {
        items(StatsTab.entries, key = { it.name }) { tab ->
            StatsSelectablePill(
                label = statsTabLabel(tab, dashboardCards),
                selected = selectedTab == tab,
                enabled = statsDashboardKeysForTab(tab, visibleDashboardKeys).isNotEmpty(),
                onClick = { onTabChange(tab) },
            )
        }
    }
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

private fun overviewRecent7DaysAmount(state: StatsUiState): Long {
    if (state.statsSource == StatsSource.LocalFallback) {
        return state.dailyTrend.sumOf { it.amountCents.coerceAtLeast(0L) }
    }
    return state.lifestyleStats?.recent7DaysAmountCents ?: 0L
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
            StatsSelectablePill(
                selected = true,
                onClick = onOpenMonthPicker,
                label = state.month.takeIf { it.isNotBlank() }?.let(::displayMonthLabel)
                    ?: stringResource(R.string.stats_filter_all_months),
                trailingIcon = { FilterTrailingIcon(Icons.Filled.ExpandMore, stringResource(R.string.stats_filter_pick_month_description)) },
            )
        }
        item {
            StatsSelectablePill(
                selected = state.selectedTag.isBlank(),
                onClick = { onTagChange("") },
                label = stringResource(R.string.stats_filter_all_tags),
            )
        }
        items(tags, key = { it }) { tag ->
            val selected = state.selectedTag.equals(tag, ignoreCase = true)
            StatsSelectablePill(
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
private fun StatsSelectablePill(
    label: String,
    selected: Boolean,
    onClick: () -> Unit,
    enabled: Boolean = true,
    trailingIcon: (@Composable () -> Unit)? = null,
) {
    val visuals = LocalThemeVisuals.current
    val controlTokens = LocalStatsTokens.current.control
    val shape = RoundedCornerShape(AppRadius.pill)
    val labelColor = when {
        !enabled -> MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.38f)
        selected -> MaterialTheme.colorScheme.primary
        else -> MaterialTheme.colorScheme.onSurfaceVariant
    }
    Row(
        modifier = Modifier
            .height(controlTokens.height)
            .clip(shape)
            .background(
                if (selected) {
                    visuals.chipSelected.copy(alpha = controlTokens.selectedAlpha)
                } else {
                    MaterialTheme.colorScheme.surface.copy(alpha = controlTokens.unselectedAlpha)
                },
            )
            .border(
                width = 1.dp,
                color = if (selected) {
                    MaterialTheme.colorScheme.primary.copy(alpha = controlTokens.borderAlpha)
                } else {
                    MaterialTheme.colorScheme.outlineVariant.copy(alpha = controlTokens.borderAlpha)
                },
                shape = shape,
            )
            .clickable(enabled = enabled, role = Role.Button, onClick = onClick)
            .padding(horizontal = controlTokens.horizontalPadding),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap, Alignment.CenterHorizontally),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            color = labelColor,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Medium,
            maxLines = 1,
        )
        trailingIcon?.invoke()
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

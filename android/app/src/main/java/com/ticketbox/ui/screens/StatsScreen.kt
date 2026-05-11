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
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.AppPageHeader
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.MonthPickerSheet
import com.ticketbox.ui.components.SafeBadge
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.screens.stats.CategoryStructureCard
import com.ticketbox.ui.screens.stats.EmptyStatsCard
import com.ticketbox.ui.screens.stats.FrequentMerchantsCard
import com.ticketbox.ui.screens.stats.LifestyleCard
import com.ticketbox.ui.screens.stats.PendingOverviewCard
import com.ticketbox.ui.screens.stats.RecentTrendCard
import com.ticketbox.ui.screens.stats.RecurringCandidatesCard
import com.ticketbox.ui.screens.stats.StatsMetricGrid
import com.ticketbox.ui.screens.stats.StatsMonthChip
import com.ticketbox.ui.screens.stats.StatsOverviewCard
import com.ticketbox.viewmodel.StatsUiState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun StatsScreen(
    state: StatsUiState,
    onMonthChange: (String) -> Unit,
    onRefresh: () -> Unit,
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
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                AppPageHeader(
                    title = "统计",
                    subtitle = "不是财务报表，是生活消费感知",
                ) {
                    SafeBadge()
                }
                StatsMonthChip(
                    selectedMonth = state.month,
                    onClick = { showMonthPicker = true },
                )
            }
        }
        state.message?.let {
            item { Text(it, color = MaterialTheme.colorScheme.secondary) }
        }
        val stats = state.stats
        if (stats == null) {
            item { EmptyStatsCard(onRefresh = onRefresh) }
        } else {
            item {
                StatsOverviewCard(
                    stats = stats,
                    recent7DaysAmountCents = state.lifestyleStats?.recent7DaysAmountCents
                        ?: state.dailyTrend.sumOf { it.amountCents },
                    comparison = state.monthComparison,
                )
            }
            item {
                StatsMetricGrid(
                    stats = stats,
                    lifestyle = state.lifestyleStats,
                    insight = state.categoryInsight,
                    budget = state.budgetProgress,
                )
            }
            val visibleCategories = stats.byCategory.filter { it.amountCents > 0L && it.count > 0 }
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
            item {
                RecentTrendCard(state.dailyTrend)
            }
            state.dataQuality?.let { dq ->
                item {
                    PendingOverviewCard(dq)
                }
            }
            if (state.recurringCandidates.isNotEmpty()) {
                item {
                    RecurringCandidatesCard(state.recurringCandidates)
                }
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

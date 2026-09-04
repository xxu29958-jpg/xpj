package com.ticketbox.ui.screens.stats

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
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
import com.ticketbox.domain.model.visibleDashboardCards
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.screens.overviewMonthComparison
import com.ticketbox.ui.screens.overviewRecent7DaysAmount
import com.ticketbox.viewmodel.DashboardLayoutUiState
import com.ticketbox.viewmodel.DataQualityLoadState
import com.ticketbox.viewmodel.RecurringListLoadState
import com.ticketbox.viewmodel.RecurringUiState
import com.ticketbox.viewmodel.ReportGoalsLoadState
import com.ticketbox.viewmodel.StatsUiState

data class OverviewModulesState(val layout: DashboardLayoutUiState, val recurring: RecurringUiState)

data class OverviewModuleActions(
    val onInbox: () -> Unit,
    val onBudget: () -> Unit,
    val onGoals: () -> Unit,
    val onRecurring: () -> Unit,
)

internal fun LazyListScope.overviewModuleItems(
    state: StatsUiState,
    overview: OverviewModulesState,
    actions: OverviewModuleActions,
    onTrend: () -> Unit,
) {
    val cards = overview.layout.cards
    if (cards == null) {
        // Until the preference can be read, retain the readable pre-personalization overview.
        item { OverviewMonthModule(state) }
        item { OverviewReportsModule(state, onTrend) }
        return
    }
    val visible = visibleDashboardCards(cards)
    if (visible.isEmpty()) item { Text(stringResource(R.string.dashboard_all_hidden)) }
    items(visible, key = DashboardCard::key) { card ->
        Column(modifier = Modifier.testTag("overview-module-${card.key}")) {
            when (card.key) {
                DASHBOARD_CARD_MONTHLY_SPEND -> OverviewMonthModule(state)
                DASHBOARD_CARD_REPORTS -> OverviewReportsModule(state, onTrend)
                DASHBOARD_CARD_BUDGET -> {
                    if (state.selectedTag.isNotBlank()) Text(stringResource(R.string.dashboard_ledger_scope))
                    StatsMetricGrid(state.budgetProgress, state.budgetProgressStatus, actions.onBudget)
                }
                DASHBOARD_CARD_RECENT_UPLOADS -> StatsInsightSurface {
                    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                        if (state.selectedTag.isNotBlank()) {
                            Text(stringResource(R.string.dashboard_ledger_scope), style = MaterialTheme.typography.bodySmall)
                        }
                        RecentUploadCard(state.lastUploadAt)
                    }
                }
                else -> OverviewLinkedModule(card, state, overview.recurring, actions)
            }
        }
    }
}

@Composable
private fun OverviewMonthModule(state: StatsUiState) {
    val stats = state.stats ?: return
    StatsInsightSurface {
        StatsOverviewCard(
            header = StatsOverviewHeaderModel(
                stats, state.statsSource, overviewRecent7DaysAmount(state), overviewMonthComparison(state),
                tagScopeInsightModel(stats, state.selectedTag),
            ),
        )
    }
}

@Composable
private fun OverviewReportsModule(state: StatsUiState, onTrend: () -> Unit) {
    StatsInsightSurface {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            Text(stringResource(R.string.stats_overview_rhythm_title), style = MaterialTheme.typography.titleMedium)
            if (state.selectedTag.isNotBlank() && state.stats != null) {
                TagScopeInsight(state.stats, state.selectedTag, state.statsSource)
            } else if (state.reportsOverview != null) {
                HeroSpendTrend(state.reportsOverview.trend, LocalCurrencyDisplay.current)
            } else {
                Text(stringResource(
                    if (state.reportsLoading) R.string.dashboard_summary_loading else R.string.stats_reports_unavailable_body,
                ))
            }
            TextButton(onClick = onTrend) { Text(stringResource(R.string.dashboard_reports_action)) }
        }
    }
}

@Composable
private fun OverviewLinkedModule(
    card: DashboardCard,
    state: StatsUiState,
    recurring: RecurringUiState,
    actions: OverviewModuleActions,
) {
    val content = when (card.key) {
        DASHBOARD_CARD_PENDING -> Triple(pendingSummary(state), R.string.dashboard_pending_action, actions.onInbox)
        DASHBOARD_CARD_GOALS -> Triple(goalsSummary(state), R.string.dashboard_goals_action, actions.onGoals)
        DASHBOARD_CARD_RECURRING -> Triple(recurringSummary(recurring), R.string.dashboard_recurring_action, actions.onRecurring)
        else -> return
    }
    StatsInsightSurface {
        Column(modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            Text(card.title, style = MaterialTheme.typography.titleMedium)
            if (state.selectedTag.isNotBlank()) {
                Text(stringResource(R.string.dashboard_ledger_scope), style = MaterialTheme.typography.bodySmall)
            }
            Text(content.first, style = MaterialTheme.typography.bodyLarge)
            TextButton(onClick = content.third) { Text(stringResource(content.second)) }
        }
    }
}

@Composable
private fun pendingSummary(state: StatsUiState): String = when {
    state.dataQualityLoadState == DataQualityLoadState.Failed -> stringResource(R.string.dashboard_summary_unavailable)
    state.dataQuality == null -> stringResource(R.string.dashboard_summary_loading)
    state.dataQuality.pendingTotal == 0 -> stringResource(R.string.dashboard_pending_empty)
    else -> stringResource(R.string.dashboard_pending_count, state.dataQuality.pendingTotal)
}

@Composable
private fun goalsSummary(state: StatsUiState): String {
    if (state.selectedTag.isNotBlank()) return stringResource(R.string.dashboard_goals_tag_scope)
    val goals = state.reportGoals.count { it.isSpendingLimit && !it.isArchived }
    return when (state.reportGoalsLoadState) {
        ReportGoalsLoadState.Failed -> stringResource(R.string.dashboard_summary_unavailable)
        ReportGoalsLoadState.Unknown, ReportGoalsLoadState.Loading -> stringResource(R.string.dashboard_summary_loading)
        ReportGoalsLoadState.Loaded -> if (goals == 0) stringResource(R.string.dashboard_goals_empty)
            else stringResource(R.string.dashboard_goals_count, goals)
    }
}

@Composable
private fun recurringSummary(state: RecurringUiState): String {
    val active = state.items.count { it.status == "active" }
    return when (state.itemsLoadState) {
        RecurringListLoadState.Failed -> stringResource(R.string.dashboard_summary_unavailable)
        RecurringListLoadState.Unknown, RecurringListLoadState.Loading -> stringResource(R.string.dashboard_summary_loading)
        RecurringListLoadState.Loaded -> if (active == 0) stringResource(R.string.dashboard_recurring_empty)
            else stringResource(R.string.dashboard_recurring_count, active)
    }
}

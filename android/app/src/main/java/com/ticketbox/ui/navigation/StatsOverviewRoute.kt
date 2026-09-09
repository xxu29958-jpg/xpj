package com.ticketbox.ui.navigation

import androidx.compose.runtime.DisposableEffect
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.ticketbox.domain.model.CurrencyProjectionGap
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.data.repository.LogicalSessionBinding
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ticketbox.ui.screens.StatsScreen
import com.ticketbox.ui.screens.stats.DashboardLayoutActions
import com.ticketbox.ui.screens.stats.OverviewModuleActions
import com.ticketbox.ui.screens.stats.OverviewModulesState
import com.ticketbox.ui.screens.stats.OverviewInteractionActions
import com.ticketbox.viewmodel.DashboardLayoutViewModel
import com.ticketbox.viewmodel.MonthlyStatsViewModel
import com.ticketbox.viewmodel.RecurringViewModel
import com.ticketbox.viewmodel.StatsBudgetViewModel
import com.ticketbox.viewmodel.StatsReportsViewModel
import com.ticketbox.viewmodel.mergeStatsUiState
import com.ticketbox.viewmodel.recurringViewModelFactory

@Composable
internal fun StatsRoute(shellState: MainShellState, screenFactory: MainScreenFactory,
    onRepairReport: (LogicalSessionBinding, ReportsOverview, CurrencyProjectionGap?) -> Unit,
) {
    val monthly: MonthlyStatsViewModel = viewModel(factory = screenFactory.repositoryViewModelFactory)
    val budget: StatsBudgetViewModel = viewModel(factory = screenFactory.repositoryViewModelFactory)
    val reports: StatsReportsViewModel = viewModel(factory = screenFactory.repositoryViewModelFactory)
    val layout: DashboardLayoutViewModel = viewModel(factory = viewModelFactory {
        initializer { DashboardLayoutViewModel(screenFactory.reportsRepository) }
    })
    val recurring: RecurringViewModel = viewModel(factory = recurringViewModelFactory(screenFactory.recurringRepository))
    val monthlyState by monthly.uiState.collectAsStateWithLifecycle()
    val budgetState by budget.uiState.collectAsStateWithLifecycle()
    val reportsState by reports.uiState.collectAsStateWithLifecycle()
    val layoutState by layout.uiState.collectAsStateWithLifecycle()
    val recurringState by recurring.uiState.collectAsStateWithLifecycle()

    LaunchedEffect(shellState.insightsDataRevision, monthlyState.ledgerReady) {
        if (shellState.insightsDataRevision > 0 && monthlyState.ledgerReady) reloadAllStats(monthly, reports)
    }
    LaunchedEffect(monthlyState.ledgerReady, monthlyState.activeLedgerId) {
        layout.refresh()
        if (monthlyState.ledgerReady) recurring.refresh()
    }
    LaunchedEffect(monthlyState.ledgerReady, monthlyState.activeLedgerId, monthlyState.month, monthlyState.selectedTag) {
        if (monthlyState.ledgerReady) reports.refresh(monthlyState.month, monthlyState.selectedTag)
    }
    LaunchedEffect(
        monthlyState.ledgerReady, monthlyState.activeLedgerId, monthlyState.month,
        monthlyState.primaryRefreshRevision,
    ) {
        if (monthlyState.ledgerReady) budget.refresh(monthlyState.month, force = true)
    }

    StatsReportExportDestination(reports, reportsState)
    RefreshReportsOnResume(reports)

    StatsScreen(
        state = mergeStatsUiState(monthlyState, budgetState, reportsState),
        overview = OverviewModulesState(layoutState, recurringState),
        actions = statsScreenActions(
            monthly, reports, shellState, monthlyState.month,
            OverviewInteractionActions(dashboardLayoutActions(layout), overviewModuleActions(shellState)),
            onRepairReport,
        ).copy(
            onRefresh = {
                reloadAllStats(monthly, reports)
                budget.refresh(monthlyState.month, force = true)
                recurring.refresh()
                layout.refresh()
            },
        ),
    )
}

internal fun reloadAllStats(monthly: MonthlyStatsViewModel, reports: StatsReportsViewModel) {
    monthly.reloadTags()
    monthly.refresh()
    val state = monthly.uiState.value
    reports.refresh(state.month, state.selectedTag)
}

internal fun dashboardLayoutActions(layout: DashboardLayoutViewModel) = DashboardLayoutActions(
    onRefresh = layout::refresh, onEdit = layout::beginEdit, onVisible = layout::setVisible,
    onMove = layout::move, onSave = layout::save, onCancel = layout::cancelEdit, onReset = layout::reset,
)

internal fun overviewModuleActions(shell: MainShellState) = OverviewModuleActions(
    onInbox = { shell.openPrimaryDomainRoot(PrimaryDomain.Inbox) },
    onBudget = { shell.openSecondaryPage(ProductSecondaryPage.Budget) },
    onGoals = { shell.openSecondaryPage(ProductSecondaryPage.SpendingGoal) },
    onRecurring = { shell.openSecondaryPage(ProductSecondaryPage.Recurring) },
)

@Composable
private fun RefreshReportsOnResume(reports: StatsReportsViewModel) {
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle, reports) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                val state = reports.uiState.value
                reports.refresh(state.month, state.selectedTag)
            }
        }
        lifecycle.addObserver(observer)
        onDispose { lifecycle.removeObserver(observer) }
    }
}

package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.ui.screens.TodayActions
import com.ticketbox.ui.screens.TodayScreen
import com.ticketbox.ui.screens.TodayScreenState
import com.ticketbox.viewmodel.MonthlyStatsViewModel
import com.ticketbox.viewmodel.PendingViewModel

@Composable
internal fun TodayRoute(
    shellState: MainShellState,
    screenFactory: MainScreenFactory,
) {
    val pendingViewModel: PendingViewModel = viewModel(factory = screenFactory.repositoryViewModelFactory)
    val monthlyStatsViewModel: MonthlyStatsViewModel = viewModel(factory = screenFactory.repositoryViewModelFactory)
    val pendingState by pendingViewModel.uiState.collectAsStateWithLifecycle()
    val monthlyState by monthlyStatsViewModel.uiState.collectAsStateWithLifecycle()
    val ledgerName = remember(monthlyState.activeLedgerId) {
        screenFactory.ledgerRepository.currentLedgerName()
    }
    val ledgerRole = remember(monthlyState.activeLedgerId) {
        screenFactory.ledgerRepository.currentLedgerRole()
    }

    LaunchedEffect(shellState.expenseEditCompletionRevision) {
        if (shellState.expenseEditCompletionRevision > 0) {
            refreshToday(pendingViewModel, monthlyStatsViewModel)
        }
    }

    LaunchedEffect(shellState.dashboardCardsRevision, monthlyState.ledgerReady) {
        if (shellState.dashboardCardsRevision > 0 && monthlyState.ledgerReady) {
            refreshToday(pendingViewModel, monthlyStatsViewModel)
        }
    }

    TodayScreen(
        state = TodayScreenState(
            pending = pendingState,
            monthly = monthlyState,
            ledgerName = ledgerName,
            ledgerRole = ledgerRole,
        ),
        actions = TodayActions(
            onRefresh = { refreshToday(pendingViewModel, monthlyStatsViewModel) },
            onOpenPending = { shellState.selectBottomTab(BottomTab.Pending.key) },
            onOpenLedger = { shellState.selectBottomTab(BottomTab.Ledger.key) },
            onOpenInsights = { shellState.selectBottomTab(BottomTab.Insights.key) },
            onUploadReceipt = {
                shellState.launchAction.post(LaunchAction.OpenImagePicker)
                shellState.selectBottomTab(BottomTab.Pending.key)
            },
            onManualEntry = {
                shellState.launchAction.post(LaunchAction.OpenManualEntry)
                shellState.selectBottomTab(BottomTab.Ledger.key)
            },
        ),
    )
}

private fun refreshToday(
    pending: PendingViewModel,
    monthly: MonthlyStatsViewModel,
) {
    pending.refresh()
    monthly.reloadTags()
    monthly.refresh()
}

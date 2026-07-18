package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavHostController
import com.ticketbox.ui.screens.pending.NeedsReviewFilter
import com.ticketbox.ui.screens.stats.DataQualityScreen
import com.ticketbox.ui.screens.stats.DataQualityRemediation
import com.ticketbox.viewmodel.LedgerDataQualityFilter
import com.ticketbox.viewmodel.MonthlyStatsViewModel

@Composable
internal fun DataQualityRoute(
    navController: NavHostController,
    currentEntry: NavBackStackEntry,
    screenFactory: MainScreenFactory,
    shellState: MainShellState,
    onBack: () -> Unit,
) {
    val insightsEntry = remember(navController, currentEntry) {
        // Data quality is reachable both from Insights and directly from Inbox.
        // A cross-domain direct entry has no Insights root on the back stack, so
        // scope the ViewModel to the secondary destination instead of crashing.
        resolveInsightsViewModelOwner(currentEntry) {
            navController.getBackStackEntry(PrimaryDomain.Insights.route)
        }
    }
    val viewModel: MonthlyStatsViewModel = viewModel(
        viewModelStoreOwner = insightsEntry,
        factory = screenFactory.repositoryViewModelFactory,
    )
    val state by viewModel.uiState.collectAsStateWithLifecycle()

    DataQualityScreen(
        state = state,
        onRefresh = viewModel::refresh,
        onRemediate = { remediation ->
            openDataQualityRemediation(shellState, remediation)
        },
        onBack = onBack,
    )
}

internal fun <T> resolveInsightsViewModelOwner(
    currentEntry: T,
    insightsEntry: () -> T,
): T = try {
    insightsEntry()
} catch (_: IllegalArgumentException) {
    currentEntry
}

internal fun openDataQualityRemediation(
    shellState: MainShellState,
    remediation: DataQualityRemediation,
) {
    val inboxFilter = when (remediation) {
        DataQualityRemediation.InboxAll -> NeedsReviewFilter.All
        DataQualityRemediation.InboxReady -> NeedsReviewFilter.ReadyToConfirm
        DataQualityRemediation.InboxMissingAmount -> NeedsReviewFilter.NeedsAmount
        DataQualityRemediation.InboxMissingMerchant -> NeedsReviewFilter.NeedsMerchant
        DataQualityRemediation.InboxMissingCategory -> NeedsReviewFilter.NeedsCategory
        DataQualityRemediation.InboxDuplicate -> NeedsReviewFilter.Duplicate
        DataQualityRemediation.TransactionsMissingCategory,
        DataQualityRemediation.TransactionsConfirmedWithoutImage,
        -> null
    }
    if (inboxFilter != null) {
        shellState.pendingFilterRequest.post(inboxFilter)
        shellState.openPrimaryDomainRoot(PrimaryDomain.Inbox)
        return
    }
    val transactionFilter = when (remediation) {
        DataQualityRemediation.TransactionsMissingCategory ->
            LedgerDataQualityFilter.MissingCategory
        DataQualityRemediation.TransactionsConfirmedWithoutImage ->
            LedgerDataQualityFilter.ConfirmedWithoutImage
        else -> return
    }
    shellState.ledgerDrill.post(LedgerDrillRequest.DataQuality(transactionFilter))
    shellState.openPrimaryDomainRoot(PrimaryDomain.Transactions)
}

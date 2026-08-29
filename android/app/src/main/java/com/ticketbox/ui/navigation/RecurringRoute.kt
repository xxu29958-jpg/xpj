package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.ui.screens.RecurringCandidateActions
import com.ticketbox.ui.screens.RecurringItemActions
import com.ticketbox.ui.screens.RecurringScreen
import com.ticketbox.ui.screens.RecurringScreenActions
import com.ticketbox.viewmodel.RecurringViewModel
import com.ticketbox.viewmodel.recurringViewModelFactory

/** Plan-owned fixed-expense destination and its production ViewModel wiring. */
@Composable
internal fun RecurringRoute(
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
    onDataChanged: () -> Unit = {},
) {
    val recurringViewModel: RecurringViewModel = viewModel(
        factory = recurringViewModelFactory(
            repository = screenFactory.recurringRepository,
            onDataChanged = onDataChanged,
        ),
    )
    val state by recurringViewModel.uiState.collectAsStateWithLifecycle()
    RecurringScreen(
        state = state,
        actions = RecurringScreenActions(
            onRefresh = recurringViewModel::refresh,
            items = RecurringItemActions(
                onPause = recurringViewModel::pause,
                onResume = recurringViewModel::resume,
                onArchive = recurringViewModel::archive,
                onRestore = recurringViewModel::restore,
                onCreate = recurringViewModel::createManual,
                onEdit = recurringViewModel::editManual,
            ),
            candidates = RecurringCandidateActions(
                onConfirmCandidate = recurringViewModel::confirmCandidate,
            ),
            onBack = onBack,
        ),
    )
}

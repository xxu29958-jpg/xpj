package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.ui.screens.RecurringCandidateActions
import com.ticketbox.ui.screens.RecurringItemActions
import com.ticketbox.ui.screens.RecurringScreen
import com.ticketbox.ui.screens.RecurringScreenActions
import com.ticketbox.viewmodel.RecurringManualSaveCommand
import com.ticketbox.viewmodel.RecurringViewModel
import com.ticketbox.viewmodel.recurringViewModelFactory

/** Plan-owned fixed-expense destination and its production ViewModel wiring. */
@Composable
internal fun RecurringRoute(
    screenFactory: MainScreenFactory,
    onBack: () -> Unit,
    onDataChanged: () -> Unit = {},
    expenseNavigation: RecurringExpenseNavigation = RecurringExpenseNavigation({}),
    financialDataRevision: Int = 0,
) {
    val recurringViewModel: RecurringViewModel = viewModel(
        factory = recurringViewModelFactory(
            originalBinding = LocalNotificationTask.current?.binding,
            repository = screenFactory.recurringRepository,
            onDataChanged = onDataChanged,
        ),
    )
    val state by recurringViewModel.uiState.collectAsStateWithLifecycle()
    val occurrenceModel = recurringOccurrenceModel(screenFactory) {
        recurringViewModel.refresh()
        onDataChanged()
    }
    LaunchedEffect(financialDataRevision) {
        if (financialDataRevision > 0) {
            recurringViewModel.refresh(retireCurrent = true)
            occurrenceModel.refresh(retireCurrent = true)
        }
    }
    RecurringScreen(
        state = notifiedRecurringPeriodState(state, occurrenceModel),
        actions = RecurringScreenActions(
            onRefresh = { recurringViewModel.refresh() },
            items = RecurringItemActions(
                onOpenOccurrence = { occurrenceModel.open(it) },
                onOpenHistory = recurringViewModel.historyTask::open,
                onPause = recurringViewModel::pause,
                onResume = recurringViewModel::resume,
                onArchive = recurringViewModel::archive,
                onRestore = recurringViewModel::restore,
                onCreate = { draft ->
                    recurringViewModel.saveManual(RecurringManualSaveCommand.Create(draft))
                },
                onEdit = { baseline, patch ->
                    recurringViewModel.saveManual(RecurringManualSaveCommand.Edit(baseline, patch))
                },
            ),
            candidates = RecurringCandidateActions(
                onConfirmCandidate = recurringViewModel::confirmCandidate,
            ),
            onBack = onBack,
        ),
    )
    RecurringOccurrenceHost(
        model = occurrenceModel,
        creation = screenFactory.repository.manualCreation,
        expenses = expenseNavigation,
        restore = RecurringPaymentRestore(
            items = state.items,
            drafts = rememberRecurringPaymentDraftStore(),
        ),
    )
    if (state.history.publicId != null) com.ticketbox.ui.screens.recurring.RecurringHistorySheet(
        state.history, recurringViewModel.historyTask::retry, recurringViewModel.historyTask::more,
        recurringViewModel.historyTask::dismiss,
    )
}

/** Uses the original period even if the reminder is opened in a later month. */
@Composable
private fun notifiedRecurringPeriodState(
    state: com.ticketbox.viewmodel.RecurringUiState,
    model: com.ticketbox.viewmodel.RecurringOccurrenceViewModel,
): com.ticketbox.viewmodel.RecurringUiState {
    val notification = LocalNotificationTask.current?.destination as? com.ticketbox.notification.NotificationDestination.Recurring
    val occurrence by model.uiState.collectAsStateWithLifecycle()
    var opened by rememberSaveable { mutableStateOf(false) }
    var missing by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(notification, state.items, state.itemsLoadState, occurrence.access) {
        val target = notification ?: return@LaunchedEffect
        if (opened || state.itemsLoadState != com.ticketbox.viewmodel.RecurringListLoadState.Loaded ||
            occurrence.access == null) return@LaunchedEffect
        val item = state.items.singleOrNull { it.publicId == target.publicId }
        missing = item == null
        if (item != null) {
            model.open(item, java.time.YearMonth.from(java.time.LocalDate.parse(target.expectedDate)).toString())
            opened = true
        }
    }
    return if (missing) state.copy(
        message = com.ticketbox.domain.model.UiText.res(com.ticketbox.R.string.notification_recurring_unavailable),
        messageTone = com.ticketbox.domain.model.MessageTone.Danger,
    ) else state
}

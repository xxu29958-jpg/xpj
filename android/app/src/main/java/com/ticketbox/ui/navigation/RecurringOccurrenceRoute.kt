package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ticketbox.data.repository.ExpenseManualCreation
import com.ticketbox.ui.screens.recurring.OccurrenceSheetActions
import com.ticketbox.ui.screens.recurring.RecurringOccurrenceSheet
import com.ticketbox.viewmodel.RecurringOccurrenceViewModel
import kotlinx.coroutines.flow.flowOf

@Composable
internal fun recurringOccurrenceModel(factory: MainScreenFactory, onChanged: () -> Unit): RecurringOccurrenceViewModel =
    viewModel(factory = viewModelFactory {
        initializer {
            RecurringOccurrenceViewModel(
                factory.recurringRepository.occurrences,
                factory.repository,
                factory.debtRepository,
                onChanged,
            )
        }
    })

@Composable
internal fun RecurringOccurrenceHost(
    model: RecurringOccurrenceViewModel,
    creation: ExpenseManualCreation,
    onOpenExpense: (Long) -> Unit,
    onRecordPayment: (RecurringPaymentTask) -> Unit,
) {
    val state by model.uiState.collectAsStateWithLifecycle()
    var taskJson by rememberSaveable { mutableStateOf<String?>(null) }
    val task = remember(taskJson) { readRecurringPaymentTask(taskJson) }
    LaunchedEffect(state.access?.binding, state.item, state.occurrence?.state, state.occurrence?.period) {
        val current = readRecurringPaymentTask(taskJson) ?: return@LaunchedEffect
        val closed = state.item == null
        val switched = state.access?.binding != current.binding
        val linked = state.occurrence?.period == current.period && state.occurrence?.state == "fulfilled"
        if (closed || switched || linked) taskJson = null
    }
    val admitted by remember(creation, task?.clientRef, task?.binding) {
        val current = task
        if (current == null) flowOf(null) else creation.observe(current.binding, current.clientRef)
    }.collectAsStateWithLifecycle(initialValue = null)
    RecurringOccurrenceSheet(
        state,
        OccurrenceSheetActions(
            onDismiss = model::dismiss,
            onRefresh = model::refresh,
            onPeriod = model::changePeriod,
            onChoose = model::choose,
            onSubmit = model::submit,
            onRecover = model::recover,
            onOpenExpense = { id -> model.dismiss(); onOpenExpense(id) },
            onRecordPayment = {
                val next = recurringPaymentTask(state, task) ?: return@OccurrenceSheetActions
                taskJson = recurringPaymentTaskJson(next)
                onRecordPayment(next)
            },
        ),
        preferredExpenseId = admitted?.acceptedExpenseId,
    )
}

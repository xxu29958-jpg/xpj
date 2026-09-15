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
import com.ticketbox.domain.model.RecurringItem
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
    items: List<RecurringItem> = emptyList(),
    drafts: RecurringPaymentDraftStore? = null,
    initialTaskJson: String? = null,
) {
    val state by model.uiState.collectAsStateWithLifecycle()
    var taskJson by rememberSaveable { mutableStateOf(initialTaskJson) }
    var userClosed by rememberSaveable { mutableStateOf(false) }
    val task = remember(taskJson) { readRecurringPaymentTask(taskJson) }
    LaunchedEffect(
        userClosed,
        state.access,
        state.item?.publicId,
        state.occurrence?.state,
        state.occurrence?.period,
        taskJson,
    ) {
        val current = readRecurringPaymentTask(taskJson) ?: return@LaunchedEffect
        val accessResolved = state.access != null
        if (!retainRecurringPaymentTask(
                current,
                userClosed = userClosed,
                accessResolved = accessResolved,
                accessBinding = state.access?.binding,
                seriesPublicId = state.item?.publicId,
                period = state.occurrence?.period,
                occurrenceState = state.occurrence?.state,
            )
        ) {
            val keepDraft = accessResolved && state.access?.binding != current.binding
            taskJson = null
            if (!keepDraft) drafts?.remove(current.clientRef)
        }
    }
    LaunchedEffect(taskJson, items, state.item, state.access?.binding, userClosed) {
        if (userClosed || state.item != null) return@LaunchedEffect
        val current = readRecurringPaymentTask(taskJson) ?: return@LaunchedEffect
        if (state.access?.binding != current.binding) return@LaunchedEffect
        val source = items.firstOrNull {
            it.publicId == current.seriesPublicId && it.ledgerId == current.binding.ledgerId
        } ?: return@LaunchedEffect
        model.open(source, current.period)
    }
    val admitted by remember(creation, task?.clientRef, task?.binding) {
        val current = task
        if (current == null) flowOf(null) else creation.observe(current.binding, current.clientRef)
    }.collectAsStateWithLifecycle(initialValue = null)
    RecurringOccurrenceSheet(
        state,
        OccurrenceSheetActions(
            onDismiss = {
                userClosed = true
                val closing = readRecurringPaymentTask(taskJson)
                taskJson = null
                closing?.let { drafts?.remove(it.clientRef) }
                model.dismiss()
            },
            onRefresh = model::refresh,
            onPeriod = model::changePeriod,
            onChoose = model::choose,
            onSubmit = model::submit,
            onRecover = model::recover,
            onOpenExpense = onOpenExpense,
            onRecordPayment = {
                val next = recurringPaymentTask(state, task) ?: return@OccurrenceSheetActions
                userClosed = false
                taskJson = recurringPaymentTaskJson(next)
                onRecordPayment(next)
            },
        ),
        preferredExpenseId = preferredPaymentExpenseId(
            task = task,
            admittedExpenseId = admitted?.acceptedExpenseId,
            binding = state.access?.binding,
            seriesPublicId = state.item?.publicId,
            period = state.occurrence?.period,
        ),
    )
}

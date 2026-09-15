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
    val focused = drafts?.remembered(state.access?.binding, state.item?.publicId, state.occurrence?.period)
        ?: task?.takeIf {
            it.binding == state.access?.binding &&
                it.seriesPublicId == state.item?.publicId &&
                it.period == state.occurrence?.period
        }
    LaunchedEffect(
        userClosed,
        state.access,
        state.item?.publicId,
        state.occurrence?.state,
        state.occurrence?.period,
        taskJson,
    ) {
        val current = readRecurringPaymentTask(taskJson)
        val accessResolved = state.access != null
        if (current != null && !retainRecurringPaymentTask(
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
        if (state.occurrence?.state == "fulfilled") {
            drafts?.remembered(state.access?.binding, state.item?.publicId, state.occurrence?.period)
                ?.let { drafts.remove(it.clientRef) }
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
    val admitted by remember(creation, focused?.clientRef, focused?.binding) {
        val current = focused
        if (current == null) flowOf(null) else creation.observe(current.binding, current.clientRef)
    }.collectAsStateWithLifecycle(initialValue = null)
    RecurringOccurrenceSheet(
        state,
        OccurrenceSheetActions(
            onDismiss = {
                val visible = focused
                if (visible != null) {
                    drafts?.remove(visible.clientRef)
                    if (task?.clientRef == visible.clientRef) {
                        userClosed = true
                        taskJson = null
                    }
                } else {
                    userClosed = true
                    val closing = readRecurringPaymentTask(taskJson)
                    taskJson = null
                    closing?.let { drafts?.remove(it.clientRef) }
                }
                model.dismiss()
            },
            onRefresh = model::refresh,
            onPeriod = model::changePeriod,
            onChoose = model::choose,
            onSubmit = model::submit,
            onRecover = model::recover,
            onOpenExpense = onOpenExpense,
            onRecordPayment = {
                val next = recurringPaymentTask(
                    state,
                    existing = task,
                    remembered = drafts?.remembered(
                        state.access?.binding,
                        state.item?.publicId,
                        state.occurrence?.period,
                    ),
                ) ?: return@OccurrenceSheetActions
                userClosed = false
                drafts?.remember(next)
                taskJson = recurringPaymentTaskJson(next)
                onRecordPayment(next)
            },
        ),
        preferredExpenseId = preferredPaymentExpenseId(
            task = focused,
            admittedExpenseId = admitted?.acceptedExpenseId,
            binding = state.access?.binding,
            seriesPublicId = state.item?.publicId,
            period = state.occurrence?.period,
        ),
    )
}

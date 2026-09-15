package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.createSavedStateHandle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ticketbox.data.repository.ExpenseManualCreation
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RecurringPaymentOrigin
import com.ticketbox.data.repository.RecurringPaymentOriginLookup
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.screens.recurring.OccurrenceSheetActions
import com.ticketbox.ui.screens.recurring.RecurringOccurrenceSheet
import com.ticketbox.viewmodel.RecurringOccurrenceUiState
import com.ticketbox.viewmodel.RecurringOccurrenceViewModel
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.onEach

internal data class RecurringPaymentRestore(
    val items: List<RecurringItem> = emptyList(),
    val drafts: RecurringPaymentDraftStore? = null,
    val initialTaskJson: String? = null,
)

private data class RecurringPaymentHostDecision(
    val clearTask: Boolean,
    val retireClientRefs: List<String>,
)

@Composable
internal fun recurringOccurrenceModel(factory: MainScreenFactory, onChanged: () -> Unit): RecurringOccurrenceViewModel =
    viewModel(factory = viewModelFactory {
        initializer {
            RecurringOccurrenceViewModel(
                factory.recurringRepository.occurrences,
                factory.repository,
                factory.debtRepository,
                onChanged,
                createSavedStateHandle(),
            )
        }
    })

private data class RecurringPaymentOriginObservation(
    val resolved: Boolean,
    val clientRef: String?,
    val conflict: Boolean = false,
)

@Composable
internal fun RecurringOccurrenceHost(
    model: RecurringOccurrenceViewModel,
    creation: ExpenseManualCreation,
    expenses: RecurringExpenseNavigation,
    restore: RecurringPaymentRestore = RecurringPaymentRestore(),
) {
    val state by model.uiState.collectAsStateWithLifecycle()
    var taskJson by rememberSaveable { mutableStateOf(restore.initialTaskJson) }
    var userClosed by rememberSaveable { mutableStateOf(false) }
    val task = remember(taskJson) { readRecurringPaymentTask(taskJson) }
    val visible = state.paymentVisible()
    val remembered = restore.drafts.adoptedTask(model.savedState, visible.identity)
    val origin = rememberRecurringPaymentOrigin(creation, visible.identity)
    val focused = remembered
        ?: task?.takeIf { it.matches(visible.identity) }
        ?: origin.clientRef?.let { recurringPaymentTask(state, admittedClientRef = it) }
    LaunchedEffect(userClosed, visible, taskJson) {
        val current = readRecurringPaymentTask(taskJson)
        val decision = recurringPaymentHostDecision(current, userClosed, visible, remembered)
        if (decision.clearTask) taskJson = null
        decision.retireClientRefs.forEach { restore.drafts?.retireTask(it) }
    }
    LaunchedEffect(taskJson, restore.items, state.item, state.access?.binding, userClosed) {
        val current = readRecurringPaymentTask(taskJson)
        val source = recurringPaymentRestoreItem(
            userClosed, state.item != null, current, state.access?.binding, restore.items,
        ) ?: return@LaunchedEffect
        model.open(source, requireNotNull(current).period)
    }
    val admitted by remember(creation, focused?.clientRef, focused?.binding) {
        val current = focused
        if (current == null) flowOf(null) else creation.observe(current.binding, current.clientRef)
    }.collectAsStateWithLifecycle(initialValue = null)
    RecurringOccurrenceSheet(
        state,
        OccurrenceSheetActions(
            onDismiss = {
                userClosed = true
                taskJson = null
                model.dismiss()
            },
            onRefresh = model::refresh,
            onPeriod = model::changePeriod,
            onChoose = model::choose,
            onSubmit = model::submit,
            onRecover = model::recover,
            onOpenExpense = expenses.onOpenExpense,
            onRecordPayment = {
                if (!origin.resolved || origin.conflict) return@OccurrenceSheetActions
                val next = recurringPaymentTask(
                    state, existing = task, remembered = remembered, admittedClientRef = origin.clientRef,
                ) ?: return@OccurrenceSheetActions
                userClosed = false
                restore.drafts?.remember(next)
                taskJson = recurringPaymentTaskJson(next)
                expenses.onRecordPayment(next)
            },
        ),
        preferredExpenseId = preferredPaymentExpenseId(focused, admitted?.acceptedExpenseId, visible.identity),
        originResolved = origin.resolved,
        originConflict = origin.conflict,
    )
}

private fun RecurringPaymentDraftStore?.adoptedTask(
    source: SavedStateHandle,
    identity: RecurringPaymentIdentity,
): RecurringPaymentTask? {
    this ?: return null
    adoptLegacyPeriodPaymentSessions(source)
    return remembered(identity.binding, identity.seriesPublicId, identity.period)
}

@Composable
private fun rememberRecurringPaymentOrigin(
    creation: ExpenseManualCreation,
    identity: RecurringPaymentIdentity,
): RecurringPaymentOriginObservation {
    var resolved by remember(identity.binding, identity.seriesPublicId, identity.period) { mutableStateOf(false) }
    val lookup by remember(creation, identity.binding, identity.seriesPublicId, identity.period) {
        val binding = identity.binding
        val series = identity.seriesPublicId
        val period = identity.period
        if (binding == null || series.isNullOrBlank() || period.isNullOrBlank()) {
            flowOf(RecurringPaymentOriginLookup.Absent).onEach { resolved = true }
        } else {
            creation.observeOrigin(binding, RecurringPaymentOrigin(series, period)).onEach { resolved = true }
        }
    }.collectAsStateWithLifecycle(initialValue = RecurringPaymentOriginLookup.Absent)
    val clientRef = (lookup as? RecurringPaymentOriginLookup.Found)?.projection?.request?.clientRef?.takeIf { it.isNotBlank() }
    return RecurringPaymentOriginObservation(resolved, clientRef, lookup is RecurringPaymentOriginLookup.Conflict)
}

private fun RecurringOccurrenceUiState.paymentVisible() = RecurringPaymentVisible(
    accessResolved = access != null,
    identity = RecurringPaymentIdentity(access?.binding, item?.publicId, occurrence?.period),
    occurrenceState = occurrence?.state,
)

private fun recurringPaymentHostDecision(
    current: RecurringPaymentTask?,
    userClosed: Boolean,
    visible: RecurringPaymentVisible,
    remembered: RecurringPaymentTask?,
): RecurringPaymentHostDecision {
    val keep = current != null && retainRecurringPaymentTask(current, userClosed, visible)
    val retire = linkedSetOf<String>()
    if (!userClosed && current != null && !retainRecurringPaymentTask(current, userClosed = false, visible)) {
        if (visible.accessResolved && current.matches(visible.identity) && visible.occurrenceState == "fulfilled") {
            retire += current.clientRef
        }
    }
    if (visible.occurrenceState == "fulfilled") {
        remembered?.clientRef?.let { retire += it }
    }
    return RecurringPaymentHostDecision(clearTask = current != null && !keep, retireClientRefs = retire.toList())
}

private fun recurringPaymentRestoreItem(
    userClosed: Boolean,
    itemOpen: Boolean,
    task: RecurringPaymentTask?,
    accessBinding: LogicalSessionBinding?,
    items: List<RecurringItem>,
): RecurringItem? {
    if (userClosed || itemOpen || task == null || accessBinding != task.binding) return null
    return items.firstOrNull { it.publicId == task.seriesPublicId && it.ledgerId == task.binding.ledgerId }
}

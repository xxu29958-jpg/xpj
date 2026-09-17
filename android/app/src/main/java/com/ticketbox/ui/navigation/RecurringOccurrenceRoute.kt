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
import com.ticketbox.data.repository.inspectOrigin
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RecurringPaymentOrigin
import com.ticketbox.data.repository.RecurringPaymentOriginLookup
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.screens.recurring.OccurrencePaymentGuard
import com.ticketbox.ui.screens.recurring.OccurrenceSheetActions
import com.ticketbox.ui.screens.recurring.RecurringOccurrenceSheet
import com.ticketbox.viewmodel.RecurringOccurrenceUiState
import com.ticketbox.viewmodel.RecurringOccurrenceViewModel
import androidx.compose.runtime.rememberCoroutineScope
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.launch
import kotlin.coroutines.cancellation.CancellationException

internal data class RecurringPaymentRestore(
    val items: List<RecurringItem> = emptyList(),
    val drafts: RecurringPaymentDraftStore? = null,
    val initialTaskJson: String? = null,
)

private data class RecurringPaymentHostDecision(
    val clearTask: Boolean,
    val retireClientRefs: List<String>,
)

private data class RecurringPaymentRetirement(
    val visible: RecurringPaymentVisible,
    val drafts: RecurringPaymentDraftStore?,
    val leftover: SavedStateHandle,
    val creation: ExpenseManualCreation,
    val refs: RecurringPaymentRetirementRefs,
)

private data class RecurringPaymentRetirementRefs(
    val clientRefs: List<String>,
    val originClientRef: String?,
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
    val origin = rememberRecurringPaymentOrigin(creation, visible.identity)
    val leftover = rememberAdoptedPaymentTask(
        LeftoverAdoptRequest(restore.drafts, model, creation, visible.identity, origin, expenses.onRecordPayment),
    )
    val guard = occurrencePaymentGuard(origin, leftover.state)
    val remembered = (leftover.state as? LegacyCompatibilityState.Ready)?.remembered
    val focused = recurringPaymentFocused(remembered, task?.takeIf { it.matches(visible.identity) }, (origin as? OriginObservation.Found)?.clientRef, state)
    CanonicalizeRecurringPaymentIdentity(RecurringPaymentCanonicalize(restore.drafts, origin, focused, task, visible.identity)) {
        taskJson = it
    }
    LaunchedEffect(userClosed, visible, taskJson, (origin as? OriginObservation.Found)?.clientRef, leftover.state) {
        if (leftover.state is LegacyCompatibilityState.Loading) return@LaunchedEffect
        val current = readRecurringPaymentTask(taskJson)
        val decision = recurringPaymentHostDecision(current, userClosed, visible, remembered)
        if (decision.clearTask) taskJson = null
        retireFulfilledPayment(RecurringPaymentRetirement(visible, restore.drafts, model.savedState, creation, RecurringPaymentRetirementRefs(decision.retireClientRefs, (origin as? OriginObservation.Found)?.clientRef)))
    }
    LaunchedEffect(taskJson, restore.items, state.item, state.access?.binding, userClosed) {
        val current = readRecurringPaymentTask(taskJson)
        val source = recurringPaymentRestoreItem(userClosed, state.item != null, current, state.access?.binding, restore.items) ?: return@LaunchedEffect
        model.open(source, requireNotNull(current).period)
    }
    val admitted by remember(creation, focused?.clientRef, focused?.binding) {
        val current = focused
        if (current == null) flowOf(null) else creation.observe(current.binding, current.clientRef)
    }.collectAsStateWithLifecycle(initialValue = null)
    RecurringOccurrenceSheet(
        state,
        OccurrenceSheetActions(
            onDismiss = { userClosed = true; taskJson = null; model.dismiss() },
            onRefresh = model::refresh,
            onPeriod = model::changePeriod,
            onChoose = model::choose,
            onSubmit = model::submit,
            onRecover = model::recover,
            onOpenExpense = expenses.onOpenExpense,
            onAbandonLeftover = leftover.abandon,
            onContinueLeftover = leftover.continueDraft,
            onRecordPayment = {
                if (!guard.resolved || guard.conflict) return@OccurrenceSheetActions
                val next = recurringPaymentTask(state, existing = task, remembered = remembered, admittedClientRef = (origin as? OriginObservation.Found)?.clientRef)
                    ?: return@OccurrenceSheetActions
                userClosed = false
                restore.drafts?.remember(next)
                taskJson = recurringPaymentTaskJson(next)
                expenses.onRecordPayment(next)
            },
        ),
        preferredExpenseId = preferredPaymentExpenseId(focused, admitted?.acceptedExpenseId, visible.identity),
        origin = guard,
    )
}

private data class LeftoverPaymentAdopt(
    val state: LegacyCompatibilityState,
    val abandon: () -> Unit = {},
    val continueDraft: () -> Unit = {},
)

private data class LeftoverAdoptRequest(
    val drafts: RecurringPaymentDraftStore?,
    val model: RecurringOccurrenceViewModel,
    val creation: ExpenseManualCreation,
    val identity: RecurringPaymentIdentity,
    val origin: OriginObservation,
    val onOpen: (RecurringPaymentTask) -> Unit,
) {
    fun snap(store: RecurringPaymentDraftStore, leftover: SavedStateHandle, notice: LegacyCompatibilityNotice? = null) =
        identity.leftoverState(
            store.legacyPeriodPaymentSessions(leftover),
            store.leftoverUnresolved(leftover, identity),
            store.remembered(identity.binding, identity.seriesPublicId, identity.period),
            notice,
        )

    suspend fun handoff(store: RecurringPaymentDraftStore, leftover: SavedStateHandle) =
        if (identity.occurrenceRowVersion == null) {
            LegacyCompatibilityState.Loading
        } else {
            runCatching { store.adoptLegacyPeriodPaymentSessions(leftover, creation, identity); snap(store, leftover) }
                .fold({ it }, { if (it is CancellationException) throw it else snap(store, leftover, LegacyCompatibilityNotice.Failed(it.message)) })
        }

    fun retireCanonical(store: RecurringPaymentDraftStore, leftover: SavedStateHandle, state: LegacyCompatibilityState): LegacyCompatibilityState {
        val continuation = (state as? LegacyCompatibilityState.Held)?.continuation ?: return state
        val found = origin as? OriginObservation.Found ?: return state
        if (found.clientRef != continuation.task.clientRef) return state
        store.removeLeftoverRecoveryMapping(leftover, identity, LeftoverMappingRemoval.CanonicalOriginTakeover)
        store.removeDraft(continuation.task.clientRef)
        return snap(store, leftover)
    }

    fun abandon(store: RecurringPaymentDraftStore, leftover: SavedStateHandle, state: LegacyCompatibilityState): LegacyCompatibilityState {
        val current = state as? LegacyCompatibilityState.Held ?: return state
        if (current.busy) return state
        return runCatching {
            store.removeLeftoverRecoveryMapping(leftover, identity, LeftoverMappingRemoval.UserAbandon)
            current.continuation?.task?.clientRef?.let(store::removeDraft)
            snap(store, leftover)
        }.getOrElse { snap(store, leftover, LegacyCompatibilityNotice.Failed(it.message)) }
    }

    suspend fun openContinuation(store: RecurringPaymentDraftStore, leftover: SavedStateHandle): LegacyCompatibilityState {
        val bound = identity.binding
        val series = identity.seriesPublicId
        val period = identity.period
        if (bound == null || series.isNullOrBlank() || period.isNullOrBlank()) {
            return snap(store, leftover, LegacyCompatibilityNotice.Conflict)
        }
        return runCatching {
            identity.leftoverContinueSnapshot(store, leftover, {
                creation.inspectOrigin(bound, RecurringPaymentOrigin(series, period, identity.occurrenceRowVersion))
            }, onOpen)
        }.fold({ it }, { if (it is CancellationException) throw it else snap(store, leftover, LegacyCompatibilityNotice.Failed(it.message)) })
    }
}

@Composable
private fun rememberAdoptedPaymentTask(input: LeftoverAdoptRequest): LeftoverPaymentAdopt {
    val store = remember(input.drafts, input.model) { input.drafts ?: RecurringPaymentDraftStore(SavedStateHandle()) }
    val handle = input.model.savedState
    var leftover by remember(store, input.model, input.creation, input.identity) {
        mutableStateOf<LegacyCompatibilityState>(LegacyCompatibilityState.Loading)
    }
    val scope = rememberCoroutineScope()
    LaunchedEffect(store, input.model, input.creation, input.identity) { leftover = input.handoff(store, handle) }
    LaunchedEffect(input.origin, leftover) { leftover = input.retireCanonical(store, handle, leftover) }
    return LeftoverPaymentAdopt(
        leftover,
        abandon = { leftover = input.abandon(store, handle, leftover) },
        continueDraft = {
            val current = leftover as? LegacyCompatibilityState.Held ?: return@LeftoverPaymentAdopt
            if (current.busy) return@LeftoverPaymentAdopt
            leftover = current.copy(busy = true)
            scope.launch { leftover = input.openContinuation(store, handle) }
        },
    )
}

private fun occurrencePaymentGuard(
    origin: OriginObservation,
    leftover: LegacyCompatibilityState,
): OccurrencePaymentGuard {
    val held = leftover as? LegacyCompatibilityState.Held
    val ready = leftover !is LegacyCompatibilityState.Loading
    val blocked = leftover is LegacyCompatibilityState.Held
    return OccurrencePaymentGuard(
        resolved = ready &&
            origin !is OriginObservation.Loading &&
            origin !is OriginObservation.Conflict &&
            (!blocked || origin is OriginObservation.Found),
        conflict = origin is OriginObservation.Conflict,
        leftoverBlocked = blocked && origin !is OriginObservation.Conflict,
        leftoverUnreadable = held?.unreadable == true && origin !is OriginObservation.Conflict,
        leftoverContinueDraft = held != null && !held.unreadable &&
            held.continuation != null && origin is OriginObservation.Absent,
        leftoverExistingOrigin = blocked && origin is OriginObservation.Found,
        leftoverActionFailed = held?.notice is LegacyCompatibilityNotice.Failed,
    )
}

private data class RecurringPaymentCanonicalize(
    val drafts: RecurringPaymentDraftStore?,
    val origin: OriginObservation,
    val focused: RecurringPaymentTask?,
    val task: RecurringPaymentTask?,
    val identity: RecurringPaymentIdentity,
)

internal fun recurringPaymentFocused(
    remembered: RecurringPaymentTask?,
    task: RecurringPaymentTask?,
    originClientRef: String?,
    state: RecurringOccurrenceUiState,
): RecurringPaymentTask? {
    val originRef = originClientRef?.takeIf { it.isNotBlank() }
    val prior = remembered ?: task
    if (originRef != null) {
        return prior?.copy(clientRef = originRef)
            ?: recurringPaymentTask(state, admittedClientRef = originRef)
    }
    return prior
}

@Composable
private fun CanonicalizeRecurringPaymentIdentity(
    input: RecurringPaymentCanonicalize,
    onTaskJson: (String) -> Unit,
) {
    val origin = input.origin
    val focused = input.focused
    val identity = input.identity
    LaunchedEffect(origin, focused?.clientRef, identity) {
        val found = origin as? OriginObservation.Found ?: return@LaunchedEffect
        val next = focused ?: return@LaunchedEffect
        if (found.clientRef != next.clientRef) return@LaunchedEffect
        if (input.drafts?.remembered(identity.binding, identity.seriesPublicId, identity.period)?.clientRef != next.clientRef) {
            input.drafts?.remember(next)
        }
        if (input.task != null && input.task.matches(identity) && input.task.clientRef != next.clientRef) {
            onTaskJson(recurringPaymentTaskJson(next))
        }
    }
}

@Composable
private fun rememberRecurringPaymentOrigin(
    creation: ExpenseManualCreation,
    identity: RecurringPaymentIdentity,
): OriginObservation {
    var originResolved by remember(identity.binding, identity.seriesPublicId, identity.period, identity.occurrenceRowVersion) { mutableStateOf(false) }
    val lookup by remember(creation, identity.binding, identity.seriesPublicId, identity.period, identity.occurrenceRowVersion) {
        val binding = identity.binding
        val series = identity.seriesPublicId
        val period = identity.period
        if (binding == null || series.isNullOrBlank() || period.isNullOrBlank()) {
            flowOf(RecurringPaymentOriginLookup.Absent).onEach { originResolved = true }
        } else {
            creation.observeOrigin(
                binding,
                RecurringPaymentOrigin(series, period, identity.occurrenceRowVersion),
            ).onEach { originResolved = true }
        }
    }.collectAsStateWithLifecycle(initialValue = RecurringPaymentOriginLookup.Absent)
    if (!originResolved) return OriginObservation.Loading
    val found = lookup as? RecurringPaymentOriginLookup.Found
    val clientRef = found?.projection?.request?.clientRef?.takeIf { it.isNotBlank() }
    return when {
        lookup is RecurringPaymentOriginLookup.Conflict || (found != null && clientRef == null) ->
            OriginObservation.Conflict
        clientRef != null -> OriginObservation.Found(clientRef)
        else -> OriginObservation.Absent
    }
}

private fun RecurringOccurrenceUiState.paymentVisible() = RecurringPaymentVisible(
    accessResolved = access != null,
    identity = RecurringPaymentIdentity(access?.binding, item?.publicId, occurrence?.period, occurrence?.rowVersion),
    occurrenceState = occurrence?.state,
)

private suspend fun retireFulfilledPayment(input: RecurringPaymentRetirement) {
    val visible = input.visible
    val refs = linkedSetOf<String>().apply {
        addAll(input.refs.clientRefs)
        if (visible.occurrenceState == "fulfilled") input.refs.originClientRef?.let { add(it) }
    }
    refs.forEach { input.drafts?.retireTask(it) }
    if (visible.occurrenceState != "fulfilled") return
    (input.drafts ?: RecurringPaymentDraftStore(SavedStateHandle()))
        .removeLeftoverRecoveryMapping(input.leftover, visible.identity, LeftoverMappingRemoval.FulfilledRetirement)
    val binding = visible.identity.binding ?: return
    val series = visible.identity.seriesPublicId?.takeIf { it.isNotBlank() } ?: return
    val period = visible.identity.period?.takeIf { it.isNotBlank() } ?: return
    val origin = RecurringPaymentOrigin(series, period, visible.identity.occurrenceRowVersion)
    refs.forEach { input.creation.retireOrigin(binding, origin, it) }
}

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

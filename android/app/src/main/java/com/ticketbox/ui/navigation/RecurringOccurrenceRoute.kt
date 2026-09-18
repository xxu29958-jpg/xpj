package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.createSavedStateHandle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import com.ticketbox.data.repository.ExpenseManualCreation
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RecurringPaymentPeriodOccupant
import com.ticketbox.data.repository.RecurringPaymentOrigin
import com.ticketbox.data.repository.RecurringPaymentOriginLookup
import com.ticketbox.data.repository.RecurringPaymentOriginRetire
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.screens.recurring.OccurrencePaymentGuard
import com.ticketbox.ui.screens.recurring.OccurrenceSheetActions
import com.ticketbox.ui.screens.recurring.RecurringOccurrenceSheet
import com.ticketbox.viewmodel.RecurringOccurrenceUiState
import com.ticketbox.viewmodel.RecurringOccurrenceViewModel
import androidx.compose.runtime.rememberCoroutineScope
import kotlinx.coroutines.flow.combine
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
    val creation: ExpenseManualCreation,
    val refs: RecurringPaymentRetirementRefs,
)

private data class RecurringPaymentRetirementRefs(
    val clientRefs: List<String>,
    val originClientRef: String?,
    val originGeneration: Long? = null,
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
    var draftEpoch by remember { mutableIntStateOf(0) }
    val task = remember(taskJson) { readRecurringPaymentTask(taskJson) }
    val visible = state.paymentVisible()
    val origin = rememberRecurringPaymentOrigin(creation, visible.identity)
    val remembered = restore.drafts?.remembered(visible.identity.binding, visible.identity.seriesPublicId, visible.identity.period)
    val prior = remembered ?: task?.takeIf { it.matches(visible.identity) }
    val localDraft = draftEpoch.let { prior?.clientRef?.let { restore.drafts?.read(it) } }
    val originRef = (origin as? OriginObservation.Found)?.clientRef
    val originExpenseId = (origin as? OriginObservation.Found)?.acceptedExpenseId ?: (origin as? OriginObservation.Occupied)?.acceptedExpenseId
    val focused = recurringPaymentFocused(remembered, task?.takeIf { it.matches(visible.identity) }, originRef, state, localDraft)
    val local = RecurringPaymentCanonicalize(
        restore.drafts, origin, focused, task, visible.identity, remembered, localDraft, expenses, state, prior,
    )
    var retireBusy by remember { mutableStateOf(false) }; var retireFailed by remember { mutableStateOf(false) }
    val guard = occurrencePaymentGuard(origin, local.held, retireBusy, retireFailed && origin is OriginObservation.Occupied)
    val scope = rememberCoroutineScope()
    CanonicalizeRecurringPaymentIdentity(local) { taskJson = it }
    LaunchedEffect(userClosed, visible, taskJson, origin) {
        val current = readRecurringPaymentTask(taskJson)
        val decision = recurringPaymentHostDecision(current, userClosed, visible, remembered)
        if (decision.clearTask) taskJson = null
        val occupied = origin as? OriginObservation.Occupied
        retireFulfilledPayment(RecurringPaymentRetirement(visible, restore.drafts, creation, RecurringPaymentRetirementRefs(decision.retireClientRefs, originRef ?: occupied?.clientRef, if (occupied != null) occupied.occurrenceRowVersion else visible.identity.occurrenceRowVersion)))
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
        local.actions(
            { userClosed = true; taskJson = null; model.dismiss() },
            model,
            { local.reopen { userClosed = false; taskJson = recurringPaymentTaskJson(it); expenses.onRecordPayment(it) } },
            { local.drop { draftEpoch += 1 } },
            { local.record { userClosed = false; taskJson = recurringPaymentTaskJson(it); expenses.onRecordPayment(it) } },
        ).copy(onRetirePriorOrigin = local.retirePrior(creation, visible.identity, scope) { b, f ->
            retireBusy = b; retireFailed = f
        }),
        preferredExpenseId = preferredPaymentExpenseId(focused, admitted?.acceptedExpenseId ?: originExpenseId, visible.identity) ?: originExpenseId,
        origin = guard,
    )
}

private fun occurrencePaymentGuard(
    origin: OriginObservation,
    localDraftHeld: Boolean,
    priorRetireBusy: Boolean = false,
    priorRetireFailed: Boolean = false,
): OccurrencePaymentGuard = OccurrencePaymentGuard(
    resolved = origin !is OriginObservation.Loading && origin !is OriginObservation.Conflict,
    conflict = origin is OriginObservation.Conflict,
    localDraftHeld = localDraftHeld,
    priorGenerationOccupied = origin is OriginObservation.Occupied,
    priorRetireBusy = priorRetireBusy,
    priorRetireFailed = priorRetireFailed,
)

private data class RecurringPaymentCanonicalize(
    val drafts: RecurringPaymentDraftStore?,
    val origin: OriginObservation,
    val focused: RecurringPaymentTask?,
    val task: RecurringPaymentTask?,
    val identity: RecurringPaymentIdentity,
    val remembered: RecurringPaymentTask?,
    val localDraft: RecurringPaymentDraft?,
    val expenses: RecurringExpenseNavigation,
    val ui: RecurringOccurrenceUiState,
    val prior: RecurringPaymentTask?,
) {
    val held: Boolean
        get() {
            val occupantRef = when (origin) {
                is OriginObservation.Found -> origin.clientRef
                is OriginObservation.Occupied -> origin.clientRef
                else -> return false
            }
            val current = focused ?: return false
            return localDraft?.clientRef == current.clientRef && current.clientRef != occupantRef
        }

    fun viewOrigin() {
        val occupant = when (origin) {
            is OriginObservation.Found -> origin.clientRef to origin.acceptedExpenseId
            is OriginObservation.Occupied -> origin.clientRef to origin.acceptedExpenseId
            else -> return
        }
        val expenseId = occupant.second
        if (expenseId != null && expenseId > 0L) {
            expenses.onOpenExpense(expenseId)
            return
        }
        val originRef = occupant.first.takeIf { it.isNotBlank() } ?: return
        expenses.onOpenSubmission(originRef)
    }

    fun retirePrior(
        creation: ExpenseManualCreation,
        identity: RecurringPaymentIdentity,
        scope: kotlinx.coroutines.CoroutineScope,
        report: (Boolean, Boolean) -> Unit,
    ): () -> Unit = retire@{
        val occupied = origin as? OriginObservation.Occupied ?: return@retire
        val binding = identity.binding ?: return@retire
        val series = identity.seriesPublicId?.takeIf { it.isNotBlank() } ?: return@retire
        val period = identity.period?.takeIf { it.isNotBlank() } ?: return@retire
        report(true, false)
        scope.launch {
            var failed = true
            try {
                failed = creation.retireOrigin(
                    binding,
                    RecurringPaymentOrigin(series, period, occupied.occurrenceRowVersion),
                    occupied.clientRef,
                ) !is RecurringPaymentOriginRetire.Retired
            } catch (cancelled: CancellationException) {
                throw cancelled
            } catch (_: Exception) {
                failed = true
            } finally {
                report(false, failed)
            }
        }
    }

    fun reopen(open: (RecurringPaymentTask) -> Unit) {
        focused?.let(open)
    }

    fun drop(changed: () -> Unit) {
        prior?.clientRef?.let { drafts?.removeDraft(it) }
        changed()
    }

    fun record(open: (RecurringPaymentTask) -> Unit) {
        if (held || origin is OriginObservation.Loading || origin is OriginObservation.Conflict) return
        if (origin is OriginObservation.Occupied) return
        val next = recurringPaymentTask(
            ui, existing = task, remembered = remembered,
            admittedClientRef = (origin as? OriginObservation.Found)?.clientRef,
        ) ?: return
        drafts?.remember(next)
        open(next)
    }

    fun actions(
        dismiss: () -> Unit,
        model: RecurringOccurrenceViewModel,
        continueLocal: () -> Unit,
        abandonLocal: () -> Unit,
        recordPayment: () -> Unit,
    ) = OccurrenceSheetActions(
        onDismiss = dismiss,
        onRefresh = model::refresh,
        onPeriod = model::changePeriod,
        onChoose = model::choose,
        onSubmit = model::submit,
        onRecover = model::recover,
        onOpenExpense = expenses.onOpenExpense,
        onOpenOrigin = ::viewOrigin,
        onContinueLocalDraft = continueLocal,
        onAbandonLocalDraft = abandonLocal,
        onRecordPayment = recordPayment,
    )
}

internal fun recurringPaymentFocused(
    remembered: RecurringPaymentTask?,
    task: RecurringPaymentTask?,
    originClientRef: String?,
    state: RecurringOccurrenceUiState,
    localDraft: RecurringPaymentDraft? = null,
): RecurringPaymentTask? {
    val originRef = originClientRef?.takeIf { it.isNotBlank() }
    val prior = remembered ?: task
    val generation = state.occurrence?.rowVersion
    if (originRef != null) {
        if (prior != null && localDraft?.clientRef == prior.clientRef && prior.clientRef != originRef) {
            return if (generation != null) prior.copy(occurrenceRowVersion = generation) else prior
        }
        val admitted = prior?.copy(clientRef = originRef)
            ?: return recurringPaymentTask(state, admittedClientRef = originRef)
        return if (generation != null) admitted.copy(occurrenceRowVersion = generation) else admitted
    }
    return if (prior != null && generation != null) prior.copy(occurrenceRowVersion = generation) else prior
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
            flowOf(RecurringPaymentOriginLookup.Absent to RecurringPaymentPeriodOccupant.Absent)
                .onEach { originResolved = true }
        } else {
            combine(
                creation.observeOrigin(
                    binding,
                    RecurringPaymentOrigin(series, period, identity.occurrenceRowVersion),
                ),
                creation.observePeriodOrigin(binding, series, period),
            ) { exact, occupant -> exact to occupant }.onEach { originResolved = true }
        }
    }.collectAsStateWithLifecycle(
        initialValue = RecurringPaymentOriginLookup.Absent to RecurringPaymentPeriodOccupant.Absent,
    )
    if (!originResolved) return OriginObservation.Loading
    return OriginObservation.fromLookups(lookup.first, lookup.second, identity.occurrenceRowVersion)
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
    val binding = visible.identity.binding ?: return
    val series = visible.identity.seriesPublicId?.takeIf { it.isNotBlank() } ?: return
    val period = visible.identity.period?.takeIf { it.isNotBlank() } ?: return
    val origin = RecurringPaymentOrigin(series, period, input.refs.originGeneration)
    refs.forEach { ref ->
        try {
            input.creation.retireOrigin(binding, origin, ref)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (_: Exception) {
        }
    }
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

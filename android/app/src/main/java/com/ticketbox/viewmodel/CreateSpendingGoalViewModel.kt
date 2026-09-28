package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.GoalEditActions
import com.ticketbox.data.repository.LedgerCalendarReader
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PendingGoalCreation
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.GoalDraft
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.parseAmountCents
import java.time.YearMonth
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class CreateSpendingGoalUiState(
    val canModify: Boolean = true,
    val name: String = "",
    val month: String = YearMonth.now().toString(),
    val monthReady: Boolean = true,
    val targetAmountInput: String = "",
    val category: String = "",
    val isSubmitting: Boolean = false,
    val formError: UiText? = null,
    val createdPublicId: String? = null,
    val ledgerCurrency: CurrencyCode? = null,
    val pending: PendingGoalCreation? = null,
    val originalSubmissionId: Long? = null,
    val creationKey: String? = null,
    val hasDraft: Boolean = false,
    val acceptanceUncertain: Boolean = false,
    val checkingOriginal: Boolean = false,
    val isViewingOriginal: Boolean = false,
) {
    val editable: Boolean get() = canModify && !isSubmitting && !checkingOriginal && !acceptanceUncertain &&
        pending == null && originalSubmissionId == null
    val canSubmit: Boolean get() = editable && monthReady && ledgerCurrency != null && name.trim().isNotEmpty() &&
        ledgerCurrency?.let { parseAmountCents(targetAmountInput, it)?.let { amount -> amount > 0L } == true } == true
    val canDiscardDraft: Boolean get() = hasDraft && !isViewingOriginal && !isSubmitting && !checkingOriginal
}

class CreateSpendingGoalViewModel(
    internal val edits: GoalEditActions,
    internal val calendars: LedgerCalendarReader? = null,
    savedStateHandle: SavedStateHandle = SavedStateHandle(),
) : ViewModel() {
    internal val store = SpendingGoalCreationDraftStore(savedStateHandle)
    internal val mutableState = MutableStateFlow(CreateSpendingGoalUiState(canModify = edits.currentAccess()?.canModify == true))
    val state: StateFlow<CreateSpendingGoalUiState> = mutableState.asStateFlow()
    internal var binding: LogicalSessionBinding? = edits.currentAccess()?.binding
    internal var task: SpendingGoalCreationDraft? = null
    internal var generation = 0L
    internal var currencyJob: Job? = null
    internal var submitJob: Job? = null
    internal var observationJob: Job? = null
    internal var lookupJob: Job? = null
    internal var submittingKey: String? = null

    init {
        activateGoalDraft()
        viewModelScope.launch {
            edits.observeAccess().collect { access ->
                if (binding != access?.binding) {
                    binding = access?.binding
                    generation += 1
                    currencyJob?.cancel(); submitJob?.cancel(); lookupJob?.cancel(); observationJob?.cancel()
                    activateGoalDraft()
                } else mutableState.value = mutableState.value.copy(canModify = access?.canModify == true)
            }
        }
    }

    fun reset(month: String? = null, originalId: Long? = null) {
        val current = task ?: return
        if (current.viewingOriginalId == originalId && (originalId != null || current.hasDraft || current.acceptedId != null)) return
        generation += 1
        currencyJob?.cancel(); lookupJob?.cancel()
        val next = if (originalId != null) current.copy(viewingOriginalId = originalId, viewFailure = null)
            else current.copy(viewingOriginalId = null, viewFailure = null).let {
                if (it.hasDraft || it.acceptedId != null || month == null) it.copy(opened = true) else it.copy(month = month.cleanGoalMonth(),
                    monthSelected = true, monthReady = true, opened = true)
            }
        store.write(next)
        activateGoalDraft()
    }

    fun retryCurrency() {
        val original = task?.takeIf { it.viewingOriginalId == null && it.acceptedId == null } ?: return
        val revision = generation
        currencyJob?.cancel()
        currencyJob = viewModelScope.launch {
            val result = edits.currency(original.binding)
            if (!isCurrentGoalTask(original) || generation != revision || task?.viewingOriginalId != null || task?.acceptedId != null) return@launch
            updateGoalDraft { it.copy(currencyCode = result.getOrNull()?.storageKey,
                failure = result.exceptionOrNull()?.goalCreationFailure(SpendingGoalFailureKind.Currency)
                    ?: it.failure?.takeUnless { failure -> failure.kind == SpendingGoalFailureKind.Currency }) }
        }
    }

    fun updateName(value: String) {
        if (state.value.editable) updateGoalDraft { it.copy(name = value, failure = null) }
    }

    fun updateTargetAmount(value: String) {
        if (!state.value.editable) return
        val currency = state.value.ledgerCurrency
        val invalid = currency != null && value.isNotBlank() && parseAmountCents(value, currency) == null
        updateGoalDraft { it.copy(amount = value,
            failure = if (invalid) SpendingGoalCreationFailure(SpendingGoalFailureKind.Amount) else null) }
    }

    fun updateCategory(value: String) {
        if (state.value.editable) updateGoalDraft { it.copy(category = value, failure = null) }
    }

    fun shiftMonth(delta: Long) {
        if (!state.value.editable) return
        val next = runCatching { YearMonth.parse(state.value.month).plusMonths(delta).toString() }.getOrNull() ?: return
        updateGoalDraft { it.copy(month = next, monthReady = true, monthSelected = true, userSelectedMonth = true, failure = null) }
    }

    fun submit() {
        val original = task ?: return
        val current = state.value
        if (!current.editable || !current.monthReady || edits.currentAccess()?.binding != original.binding ||
            edits.currentAccess()?.canModify != true) return
        val currency = current.ledgerCurrency
        val amount = currency?.let { parseAmountCents(current.targetAmountInput, it) }
        val failure = when {
            currency == null -> SpendingGoalCreationFailure(SpendingGoalFailureKind.Currency)
            current.name.trim().isBlank() || amount == null || amount <= 0 -> SpendingGoalCreationFailure(SpendingGoalFailureKind.Validation)
            else -> null
        }
        if (failure != null) { updateGoalDraft { it.copy(failure = failure) }; return }
        val draft = GoalDraft(current.name, current.month, requireNotNull(amount),
            homeCurrencyCode = requireNotNull(currency).storageKey, category = current.category)
        updateGoalDraft { it.copy(failure = null) }
        val published = requireNotNull(task)
        submittingKey = published.creationKey
        mutableState.value = state.value.copy(isSubmitting = true)
        submitJob = viewModelScope.launch { submitGoalTask(published, draft) }
    }

    fun retryOriginal() {
        if (state.value.isSubmitting || state.value.checkingOriginal) return
        observeGoalCreations()
        if (task?.viewingOriginalId == null) lookupGoalCreation()
    }

    fun discardDraft() {
        val current = task ?: return
        if (state.value.isSubmitting || state.value.checkingOriginal || current.viewingOriginalId != null) return
        generation += 1
        currencyJob?.cancel(); lookupJob?.cancel()
        store.remove(current)
        activateGoalDraft()
    }

    fun consumeCreated() {
        val current = task ?: return
        if (current.viewingOriginalId != null) store.write(current.copy(viewingOriginalId = null, viewFailure = null))
        else store.remove(current)
        generation += 1
        activateGoalDraft()
    }

    fun recover(pending: PendingGoalCreation, drop: Boolean) {
        val current = task ?: return
        if (state.value.isSubmitting || state.value.pending?.row != pending.row) return
        val revision = generation
        submittingKey = current.creationKey
        mutableState.value = state.value.copy(isSubmitting = true, formError = null)
        submitJob = viewModelScope.launch {
            try {
                val result = edits.recoverCreation(current.binding, pending, drop)
                if (!isCurrentGoalTask(current) || generation != revision) return@launch
                if (result.isSuccess && drop) {
                    if (current.viewingOriginalId != null) store.write(current.copy(viewingOriginalId = null, viewFailure = null)) else store.remove(current)
                    activateGoalDraft()
                } else {
                    val failure = result.exceptionOrNull()?.goalCreationFailure(SpendingGoalFailureKind.Recovery)
                    val settled = store.settle(current) {
                        if (it.viewingOriginalId != null) it.copy(viewFailure = failure) else it.copy(failure = failure)
                    }
                    if (settled != null) task = settled
                    mutableState.value = state.value.copy(formError = failure?.text())
                }
            } finally {
                if (submittingKey == current.creationKey) {
                    submittingKey = null
                    if (isCurrentGoalTask(current)) mutableState.value = state.value.copy(isSubmitting = false)
                }
            }
        }
    }
}

internal fun String.cleanGoalMonth(): String =
    runCatching { YearMonth.parse(trim()).toString() }.getOrDefault(YearMonth.now().toString())

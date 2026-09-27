package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.*
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.withLock
import java.math.BigDecimal

/** Reopening reads the raw original draft and the independently cached server projection. */
internal fun BudgetAdviceViewModel.openArrangementMonth() {
    val snapshot = _state.value
    val binding = snapshot.binding ?: return
    val generation = ++arrangementLoadGeneration
    _state.update { it.copy(arrangementLoading = true) }
    arrangementDraftLoad = viewModelScope.launch {
        val draft = repository.arrangementDraft(binding, snapshot.month)
        if (_state.value.binding != binding || _state.value.month != snapshot.month || generation != arrangementLoadGeneration) return@launch
        _state.update { it.copy(arrangementDraft = draft) }
        refreshArrangement()
    }
}

fun BudgetAdviceViewModel.refreshArrangement() {
    val snapshot = _state.value
    val binding = snapshot.binding ?: return
    val generation = ++arrangementLoadGeneration
    _state.update { it.copy(arrangementLoading = true) }
    viewModelScope.launch {
        val read = repository.arrangement(binding, snapshot.month)
        if (_state.value.binding != binding || _state.value.month != snapshot.month || generation != arrangementLoadGeneration) return@launch
        val denied = read.exceptionOrNull()?.takeIf { it.isReadAccessDenied() }
        if (denied != null) { rejectArrangementRead(denied); return@launch }
        if (_state.value.arrangementDraft?.edited != true && _state.value.trialRequest != null) requestGeneration += 1
        _state.update { it.arrangementRefreshed(read) }
        refreshInputs()
        _state.value.inputs?.homeCurrencyCode?.let(::seedArrangementDraft)
    }
}

internal fun BudgetAdviceViewModel.seedArrangementDraft(home: String) {
    if (_state.value.arrangementRead != null && _state.value.arrangementDraft == null)
        _state.update { it.copy(arrangementDraft = MonthlyArrangementDraft(home, "0", "0", null)) }
}

fun BudgetAdviceViewModel.editArrangement(savings: Boolean, value: String) {
    val snapshot = _state.value
    val binding = snapshot.binding ?: return
    val draft = snapshot.arrangementDraft ?: return
    if (snapshot.arrangementBusy) return
    val changed = if (savings) draft.copy(savings = value, edited = true) else draft.copy(buffer = value, edited = true)
    val initialRead = snapshot.reportingHomeCurrencyCode == null && snapshot.inputsLoading && snapshot.trialRequest == null
    requestGeneration += 1
    if (!initialRead) inputGeneration += 1
    _state.update { it.copy(arrangementDraft = changed, trialRequest = null, inputs = null, inputsLoading = initialRead,
        result = null, loadState = BudgetAdviceLoadState.Idle, arrangementMessage = UiText.res(R.string.arrangement_edited)) }
    viewModelScope.launch { arrangementDraftWrites.withLock { repository.storeArrangementDraft(binding, snapshot.month, changed) } }
}

fun BudgetAdviceViewModel.trialArrangement() {
    if (_state.value.reportingHomeCurrencyCode == null) return
    val request = runCatching { requireNotNull(_state.value.arrangementDraft).request() }
        .getOrElse { error -> _state.update { it.copy(arrangementMessage = error.toUiText(R.string.arrangement_invalid_amount)) }; return }
    requestGeneration += 1
    _state.update { it.copy(trialRequest = request, inputs = null, result = null,
        loadState = BudgetAdviceLoadState.Idle, arrangementMessage = null) }
    refreshInputs()
}

fun BudgetAdviceViewModel.saveArrangement() {
    val snapshot = _state.value
    val binding = snapshot.binding ?: return
    val draft = snapshot.arrangementDraft ?: return
    if (snapshot.arrangementBusy || !snapshot.canRequest || snapshot.arrangementRead == null ||
        snapshot.arrangementPending.any { it.intent?.month == snapshot.month && !it.isConfirmed }) return
    val request = runCatching { draft.request() }.getOrElse { error ->
        _state.update { it.copy(arrangementMessage = error.toUiText(R.string.arrangement_invalid_amount)) }; return }
    _state.update { it.copy(arrangementBusy = true, arrangementDraft = draft.copy(edited = false)) }
    viewModelScope.launch {
        val saved = repository.enqueueArrangement(binding, snapshot.month, request)
        // Only the queue now owns this exact draft. A binding switch never removes another draft.
        if (saved.isSuccess) arrangementDraftWrites.withLock { repository.consumeArrangementDraft(binding, snapshot.month, draft) }
        if (_state.value.binding != binding || _state.value.month != snapshot.month) return@launch
        _state.update { it.copy(arrangementBusy = false, arrangementMessage = saved.exceptionOrNull()?.toUiText(R.string.arrangement_save_failed) ?: UiText.res(R.string.arrangement_queued),
            arrangementDraft = if (saved.isFailure) draft else it.arrangementDraft) }
    }
}

internal fun BudgetAdviceViewModel.observeArrangementSubmissions(binding: LogicalSessionBinding) {
    arrangementObservation = viewModelScope.launch {
        var seen: Set<Long>? = null
        repository.observeArrangements(binding).collect { rows ->
            if (_state.value.binding != binding) return@collect
            val confirmed = rows.filter { it.isConfirmed }.map { it.row.id }.toSet()
            val fresh = seen?.let { confirmed - it }.orEmpty()
            seen = confirmed
            _state.update { it.copy(arrangementPending = rows) }
            if (fresh.isNotEmpty()) {
                // A real ACK also waits for the unsent original before projecting a saved value.
                arrangementDraftLoad?.join()
                if (_state.value.binding != binding) return@collect
                val receipt = rows.filter { it.row.id in fresh && it.intent?.month == _state.value.month }
                    .maxByOrNull { it.receipt?.rowVersion ?: 0 }?.receipt
                if (receipt != null) {
                    requestGeneration += 1
                    _state.update { it.copy(trialRequest = null, inputs = null, result = null, loadState = BudgetAdviceLoadState.Idle,
                        arrangementDraft = if (it.arrangementDraft?.edited == true) it.arrangementDraft else receipt.draft(),
                        arrangementMessage = UiText.res(R.string.arrangement_save_confirmed), arrangementHistoryLoaded = false) }
                    refreshArrangement()
                }
            }
        }
    }
}

fun BudgetAdviceViewModel.loadArrangementHistory(more: Boolean = false) {
    val snapshot = _state.value
    val binding = snapshot.binding ?: return
    if (snapshot.arrangementBusy || (more && snapshot.arrangementHistoryNext == null)) return
    _state.update { it.copy(arrangementBusy = true) }
    viewModelScope.launch {
        val read = repository.arrangementHistory(binding, snapshot.month, if (more) snapshot.arrangementHistoryNext else null)
        if (_state.value.binding != binding || _state.value.month != snapshot.month) return@launch
        val denied = read.exceptionOrNull()?.takeIf { it.isReadAccessDenied() }
        if (denied != null) { rejectArrangementRead(denied); return@launch }
        _state.update { it.arrangementHistoryRefreshed(read, more) }
    }
}

/** Conflict review captures fresh OCC explicitly; retry always uses the old command unchanged. */
fun BudgetAdviceViewModel.reviewArrangement(pending: PendingMonthlyArrangement) {
    val snapshot = _state.value
    val binding = snapshot.binding ?: return
    val original = pending.intent ?: return
    if (snapshot.arrangementBusy) return
    _state.update { it.copy(arrangementBusy = true) }
    viewModelScope.launch {
        val read = repository.arrangement(binding, original.month)
        if (_state.value.binding != binding) return@launch
        val denied = read.exceptionOrNull()?.takeIf { it.isReadAccessDenied() }
        if (denied != null) { rejectArrangementRead(denied); return@launch }
        val verified = read.getOrNull()?.takeUnless { it.fromCache }
        val record = verified?.response?.arrangement
        val error = read.exceptionOrNull()?.toUiText(R.string.arrangement_load_failed)
            ?: if (verified == null) UiText.res(R.string.arrangement_review_offline) else null
        _state.update { it.copy(arrangementBusy = false, arrangementMessage = error) }
        if (verified == null) return@launch
        val request = original.request
        val currency = requireNotNull(CurrencyCode.fromStorageKeyOrNull(request.homeCurrencyCode))
        val draft = MonthlyArrangementDraft(request.homeCurrencyCode,
            BigDecimal.valueOf(request.savingsTargetCents, currency.minorUnitDigits).toPlainString(),
            BigDecimal.valueOf(request.reservedBufferCents, currency.minorUnitDigits).toPlainString(), record?.rowVersion, true)
        // Original stays in queue until the user explicitly stops it; reviewed draft cannot bypass it.
        requestGeneration += 1
        _state.update { it.copy(month = original.month, arrangementRead = verified, arrangementDraft = draft, trialRequest = null,
            inputs = null, result = null, loadState = BudgetAdviceLoadState.Idle,
            arrangementHistory = emptyList(), arrangementHistoryLoaded = false,
            arrangementMessage = UiText.res(R.string.arrangement_reviewed)) }
        arrangementDraftWrites.withLock { repository.storeArrangementDraft(binding, original.month, draft) }
        refreshInputs()
    }
}

/** Withdraw query displays, while the original draft and command receipts remain recoverable. */
internal fun BudgetAdviceViewModel.rejectArrangementRead(error: Throwable) {
    arrangementLoadGeneration += 1
    inputGeneration += 1
    requestGeneration += 1
    repository.invalidateBudgetAdvice()
    _state.update { it.arrangementReadRefused(error) }
}
fun BudgetAdviceViewModel.recoverArrangement(pending: PendingMonthlyArrangement, drop: Boolean) {
    val snapshot = _state.value
    val binding = snapshot.binding ?: return
    if (snapshot.arrangementBusy) return
    _state.update { it.copy(arrangementBusy = true) }
    viewModelScope.launch {
        val recovered = repository.recoverArrangement(binding, pending, drop)
        if (_state.value.binding == binding) _state.update { it.copy(arrangementBusy = false,
            arrangementMessage = recovered.exceptionOrNull()?.toUiText(R.string.arrangement_save_failed)
                ?: UiText.res(if (drop) R.string.arrangement_stopped else R.string.arrangement_retrying)) }
    }
}

package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PendingExpenseCorrection
import com.ticketbox.data.repository.correctionRefreshVersion
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.canInitiateBillSplit
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Establish the durable snapshot before reads, so historical delivery is not a new edit. */
internal fun ExpenseFactViewModel.observeCorrectionSubmissions(onBindingSnapshot: () -> Unit) {
    viewModelScope.launch {
        repository.observeCorrections().collect { observation ->
            val previous = _uiState.value.correctionAccess
            if (previous != null && previous.binding != observation.access?.binding) {
                correctionSplitMemberGeneration++
                correctionBaseline = null
                correctionBinding = null
                correctionOriginalItems = null
                correctionOriginalSplits = null
                observedCorrectionCompletions = null
                factBundleLoadGeneration++
                revisionLoadGeneration++
                expenseLoadGeneration++
                expenseReadInFlightGeneration = null
                itemsLoadGeneration++
                splitsLoadGeneration++
                thumbnailLoadGeneration++
                fullImageLoadGeneration++
                _uiState.value = ExpenseFactUiState(readOnly = true)
            }
            val corrections = observation.corrections.filter { it.expenseId == expenseId }
            val done = corrections.filter { it.delivered }.map { it.row.id }.toSet()
            val previousDone = observedCorrectionCompletions
            val newlyDelivered = if (previousDone == null) emptyList() else {
                corrections.filter { it.delivered && it.row.id !in previousDone }
            }
            val refreshAcknowledged = _uiState.value.corrections.any { previousCorrection ->
                previousCorrection.refreshRequired && corrections.none {
                    it.row.id == previousCorrection.row.id && it.refreshRequired
                }
            }
            val refreshAfterAcknowledgment = shouldRefreshAcknowledgedRoot(refreshAcknowledged)
            val needsRefresh = newlyDelivered.isNotEmpty() || refreshAfterAcknowledgment
            val requiredVersion = corrections.filter { it.refreshRequired }
                .mapNotNull { correctionRefreshVersion(it.row.lastError) }.maxOrNull() ?: 0L
            _uiState.update {
                it.copy(
                    correctionAccess = observation.access,
                    corrections = corrections,
                    requiredRootRowVersion = maxOf(it.requiredRootRowVersion, requiredVersion),
                    readOnly = observation.access?.canModify != true,
                    expenseLoading = it.expenseLoading || needsRefresh,
                    expenseLoadState = if (needsRefresh) {
                        ExpenseDetailDataLoadState.Loading
                    } else it.expenseLoadState,
                )
            }
            observedCorrectionCompletions = done
            when {
                observation.access == null -> observedCorrectionCompletions = null
                previousDone == null -> onBindingSnapshot()
                else -> refreshNewCorrectionCompletions(newlyDelivered, refreshAfterAcknowledgment)
            }
        }
    }
}

private fun ExpenseFactViewModel.shouldRefreshAcknowledgedRoot(acknowledged: Boolean): Boolean {
    val state = _uiState.value
    return acknowledged && (state.expense?.rowVersion ?: 0L) < state.requiredRootRowVersion &&
        expenseReadInFlightGeneration == null && !state.initialRootVerificationPending &&
        state.factBundleLoadState != ExpenseDetailDataLoadState.Loading
}

private fun ExpenseFactViewModel.refreshNewCorrectionCompletions(
    corrections: List<PendingExpenseCorrection>,
    refreshAfterAcknowledgment: Boolean,
) {
    if (corrections.isEmpty() && !refreshAfterAcknowledgment) return
    val changesAdvice = corrections.any {
        val request = it.intent?.request
        request?.originalAmountMinor != null || request?.originalCurrencyCode != null ||
            request?.category != null || request?.expenseTime?.changed == true
    }
    _uiState.update { it.copy(factBundle = null, message = null,
        doneAdviceInputsChanged = it.doneAdviceInputsChanged || changesAdvice) }
    refreshCorrectionFact()
}

/** Reconcile a route's initial root with its existing bound Room projection without requiring a network read. */
internal fun ExpenseFactViewModel.verifyInitialExpenseFromCache(onRefreshRequired: () -> Unit) {
    val binding = _uiState.value.correctionAccess?.binding ?: return
    val generation = ++expenseLoadGeneration
    expenseReadInFlightGeneration = generation
    _uiState.update { it.copy(initialRootVerificationPending = true, expenseLoading = true,
        expenseLoadState = ExpenseDetailDataLoadState.Loading) }
    viewModelScope.launch {
        if (!isCurrentInitialRootRequest(binding, generation)) return@launch
        val cached = repository.fetchExpenseFromLocalCache(expenseId)
        if (!isCurrentInitialRootRequest(binding, generation)) return@launch
        val currentBinding = repository.observeCorrections().first().access?.binding
        if (currentBinding != binding || !isCurrentInitialRootRequest(binding, generation)) return@launch
        cached.onSuccess { expense ->
            _uiState.update {
                val current = it.expense
                val adopted = if (current == null || expense.rowVersion >= current.rowVersion) expense else current
                it.copy(expense = adopted, initialRootVerificationPending = false, expenseLoading = false,
                    expenseLoadState = ExpenseDetailDataLoadState.Loaded, expenseStale = false,
                    expenseLoadMessage = null)
            }
            if (_uiState.value.expense?.canInitiateBillSplit(_uiState.value.readOnly) == true) {
                loadBillSplitSent(onlyIfUnknown = true)
            }
            if (_uiState.value.corrections.any { it.refreshRequired } ||
                (_uiState.value.expense?.rowVersion ?: 0L) < _uiState.value.requiredRootRowVersion
            ) onRefreshRequired()
        }.onFailure {
            _uiState.update { it.copy(initialRootVerificationPending = false, expenseLoading = true,
                expenseLoadState = ExpenseDetailDataLoadState.Loading) }
            // The old confirmed cache may have been retired by an authoritative non-confirmed read.
            // Keep known content visible, but only the existing fresh-read owner can restore write eligibility.
            onRefreshRequired()
        }
    }.invokeOnCompletion {
        if (expenseReadInFlightGeneration == generation) expenseReadInFlightGeneration = null
    }
}

private fun ExpenseFactViewModel.isCurrentInitialRootRequest(binding: LogicalSessionBinding, generation: Long): Boolean =
    generation == expenseLoadGeneration && binding == _uiState.value.correctionAccess?.binding

/** New relationships use the adopted root; reads and existing-relation cancellation remain available. */
internal fun ExpenseFactViewModel.blockUnreadyFactWrite(expectedRowVersion: Long? = null): Boolean {
    if (blockReadOnlyWrite()) return true
    val state = _uiState.value
    if (state.authoritativeRootReady &&
        (expectedRowVersion == null || state.expense?.rowVersion == expectedRowVersion)
    ) return false
    _uiState.update {
        it.copy(
            message = UiText.res(R.string.expense_fact_snapshot_actions_unavailable),
            messageTone = MessageTone.Neutral,
        )
    }
    return true
}

fun ExpenseFactViewModel.refreshCorrectionFact() {
    retryLoadExpense()
    loadExpenseFactBundle()
    loadExpenseItems()
    loadExpenseSplits()
    loadExpenseRevisions()
}

fun ExpenseFactViewModel.recoverCorrection(rowId: Long, drop: Boolean) {
    val binding = _uiState.value.correctionAccess?.binding ?: return
    if (_uiState.value.correctionRecoveryBusy) return
    _uiState.update { it.copy(correctionRecoveryBusy = true) }
    viewModelScope.launch {
        repository.recoverCorrection(binding, rowId, drop)
            .onSuccess { if (drop) refreshCorrectionFact() }
            .onFailure { error -> _uiState.update { it.copy(message = error.toUiText(R.string.expense_correction_failed),
                messageTone = MessageTone.Danger) } }
        _uiState.update { it.copy(correctionRecoveryBusy = false) }
    }
}

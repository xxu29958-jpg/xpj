package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PendingExpenseCorrection
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.canInitiateBillSplit
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

internal fun ExpenseFactViewModel.refreshNewCorrectionCompletions(
    corrections: List<PendingExpenseCorrection>,
    refreshRequired: Boolean,
) {
    if (corrections.isEmpty() && !refreshRequired) return
    val changesAdvice = corrections.any {
        val request = it.intent?.request
        request?.originalAmountMinor != null || request?.originalCurrencyCode != null ||
            request?.category != null || request?.expenseTime?.changed == true
    }
    _uiState.update { it.copy(factBundle = null, message = null,
        doneAdviceInputsChanged = it.doneAdviceInputsChanged || changesAdvice) }
    if (!refreshRequired && corrections.isNotEmpty() && corrections.none { it.refreshRequired }) {
        verifyExpenseFromCache(afterRowVersion = corrections.maxOf { it.row.expectedRowVersion }) {
            refreshCorrectionFact()
        }
    } else {
        refreshCorrectionFact()
    }
}

/** Reconcile a route's initial root with its existing bound Room projection without requiring a network read. */
internal fun ExpenseFactViewModel.verifyInitialExpenseFromCache(onRefreshRequired: () -> Unit) {
    verifyExpenseFromCache(afterRowVersion = null, onRefreshRequired = onRefreshRequired)
}

/** A newly delivered correction additionally requires a cached root beyond its original OCC. */
private fun ExpenseFactViewModel.verifyExpenseFromCache(afterRowVersion: Long?, onRefreshRequired: () -> Unit) {
    val binding = _uiState.value.correctionAccess?.binding ?: return
    val generation = ++expenseLoadGeneration
    expenseReadInFlightGeneration = generation
    _uiState.update { it.copy(initialRootVerificationPending = true, expenseLoading = true,
        expenseLoadState = ExpenseDetailDataLoadState.Loading) }
    viewModelScope.launch {
        if (!isCurrentInitialRootRequest(binding, generation)) return@launch
        val cached = repository.fetchExpenseFromLocalCache(expenseId).getOrNull()
        if (!isCurrentInitialRootRequest(binding, generation)) return@launch
        val currentBinding = repository.observeCorrections().first().access?.binding
        if (currentBinding != binding || !isCurrentInitialRootRequest(binding, generation)) return@launch
        if (cached == null || (afterRowVersion != null &&
                (cached.rowVersion <= afterRowVersion || cached.rowVersion < _uiState.value.requiredRootRowVersion))) {
            _uiState.update { it.copy(initialRootVerificationPending = false, expenseLoading = true,
                expenseLoadState = ExpenseDetailDataLoadState.Loading) }
            onRefreshRequired()
            return@launch
        }
        if (!adoptVerifiedCachedRoot(cached)) onRefreshRequired()
        else if (afterRowVersion != null) refreshCorrectionDetails()
    }.invokeOnCompletion {
        if (expenseReadInFlightGeneration == generation) expenseReadInFlightGeneration = null
    }
}

private fun ExpenseFactViewModel.adoptVerifiedCachedRoot(cached: Expense): Boolean {
    _uiState.update {
        val current = it.expense
        val adopted = if (current == null || cached.rowVersion >= current.rowVersion) cached else current
        it.copy(expense = adopted, initialRootVerificationPending = false, expenseLoading = false,
            expenseLoadState = ExpenseDetailDataLoadState.Loaded, expenseStale = false,
            expenseLoadMessage = null)
    }
    if (_uiState.value.expense?.canInitiateBillSplit(_uiState.value.readOnly) == true) {
        loadBillSplitSent(onlyIfUnknown = true)
    }
    val state = _uiState.value
    state.expense?.let { loadThumbnailFor(it) }
    return state.expenseRefreshRequirements.isEmpty() && state.corrections.none { it.refreshRequired } &&
        (state.expense?.rowVersion ?: 0L) >= state.requiredRootRowVersion
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
    refreshCorrectionDetails()
}

private fun ExpenseFactViewModel.refreshCorrectionDetails() {
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
        val result = repository.recoverCorrection(binding, rowId, drop)
        if (_uiState.value.correctionAccess?.binding != binding) return@launch
        result
            .onSuccess { if (drop) refreshCorrectionFact() }
            .onFailure { error -> _uiState.update { it.copy(message = error.toUiText(R.string.expense_correction_failed),
                messageTone = MessageTone.Danger) } }
        _uiState.update { it.copy(correctionRecoveryBusy = false) }
    }
}

package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.PendingExpenseCorrection
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
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
            _uiState.update {
                it.copy(
                    correctionAccess = observation.access,
                    corrections = corrections,
                    readOnly = observation.access?.canModify != true,
                    expenseLoading = it.expenseLoading || newlyDelivered.isNotEmpty(),
                    expenseLoadState = if (newlyDelivered.isNotEmpty()) {
                        ExpenseDetailDataLoadState.Loading
                    } else it.expenseLoadState,
                )
            }
            observedCorrectionCompletions = done
            when {
                observation.access == null -> observedCorrectionCompletions = null
                previousDone == null -> onBindingSnapshot()
                else -> refreshNewCorrectionCompletions(newlyDelivered)
            }
        }
    }
}

private fun ExpenseFactViewModel.refreshNewCorrectionCompletions(corrections: List<PendingExpenseCorrection>) {
    if (corrections.isEmpty()) return
    val changesAdvice = corrections.any {
        val request = it.intent?.request
        request?.originalAmountMinor != null || request?.originalCurrencyCode != null ||
            request?.category != null || request?.expenseTime?.changed == true
    }
    _uiState.update { it.copy(factBundle = null, message = null,
        doneAdviceInputsChanged = it.doneAdviceInputsChanged || changesAdvice) }
    refreshCorrectionFact()
}

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

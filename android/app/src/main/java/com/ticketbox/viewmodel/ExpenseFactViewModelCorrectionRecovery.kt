package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.PendingExpenseCorrection
import com.ticketbox.domain.model.MessageTone
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
                _uiState.value = ExpenseFactUiState(readOnly = true)
            }
            val corrections = observation.corrections.filter { it.expenseId == expenseId }
            _uiState.update { it.copy(correctionAccess = observation.access, corrections = corrections,
                readOnly = observation.access?.canModify != true) }
            val done = corrections.filter { it.delivered }.map { it.row.id }.toSet()
            val previousDone = observedCorrectionCompletions
            observedCorrectionCompletions = done
            when {
                observation.access == null -> observedCorrectionCompletions = null
                previousDone == null -> onBindingSnapshot()
                else -> refreshNewCorrectionCompletions(corrections.filter { it.delivered && it.row.id !in previousDone })
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

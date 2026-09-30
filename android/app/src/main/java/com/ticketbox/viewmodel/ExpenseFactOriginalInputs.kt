package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.ExpenseOffsetFact
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

internal fun ExpenseFactViewModel.loadFactOriginalInputs() {
    val binding = _uiState.value.correctionAccess?.binding ?: return
    val generation = ++factInputLoadGeneration
    _uiState.update { it.copy(factInputsReady = false, factInputError = null) }
    viewModelScope.launch(start = CoroutineStart.UNDISPATCHED) {
        val result = repository.loadFactInputs(binding, expenseId)
        if (_uiState.value.correctionAccess?.binding != binding || generation != factInputLoadGeneration) return@launch
        result.onSuccess { originals ->
            try {
                originals.forEach { ExpenseFactInputCodec.decode(it.json, expenseId) }
                lateinit var session: ExpenseFactInputSession
                session = ExpenseFactInputSession(binding, expenseId, repository, viewModelScope, originals) {
                    if (factInputSession === session) _uiState.update { it.copy(factInputKeys = session.keys,
                        factInputWriting = session.writing,
                        factInputError = session.error?.toUiText(R.string.expense_fact_input_save_failed)) }
                }
                factInputSession = session
                restoreCorrectionInput()
                _uiState.update { it.copy(factInputsReady = true, factInputKeys = session.keys) }
            } catch (_: IllegalArgumentException) {
                _uiState.update { it.copy(factInputError = UiText.res(R.string.expense_fact_input_load_failed)) }
            } catch (_: com.squareup.moshi.JsonDataException) {
                _uiState.update { it.copy(factInputError = UiText.res(R.string.expense_fact_input_load_failed)) }
            } catch (_: com.squareup.moshi.JsonEncodingException) {
                _uiState.update { it.copy(factInputError = UiText.res(R.string.expense_fact_input_load_failed)) }
            }
        }.onFailure { error ->
            _uiState.update { it.copy(factInputError = error.toUiText(R.string.expense_fact_input_load_failed)) }
        }
    }
}

internal fun ExpenseFactViewModel.restoreCorrectionInput(): Boolean {
    val session = factInputSession ?: return false
    val input = session.original("correction") ?: return false
    val draft = session.draft("correction") ?: return false
    correctionBaseline = draft.baseline
    correctionBinding = input.binding
    correctionOriginalItems = draft.originalItems
    correctionOriginalSplits = draft.originalSplits
    _uiState.update { it.copy(correction = requireNotNull(draft.correction).form(draft.baseline)) }
    return true
}

internal fun ExpenseFactViewModel.keepCorrectionInput(review: Boolean = false) {
    val baseline = correctionBaseline ?: return
    factInputSession?.keep("correction", ExpenseFactInputDraft(baseline,
        correction = _uiState.value.correction.originalValues(), originalItems = correctionOriginalItems,
        originalSplits = correctionOriginalSplits), review)
}

internal fun ExpenseFactViewModel.keepOffsetInput(review: Boolean = false) {
    val form = _uiState.value.offsetForm
    val baseline = form.sourceExpense ?: return
    factInputSession?.keep(form.inputKey(), ExpenseFactInputDraft(baseline, offsetKind = form.kind,
        amountText = form.amountText, accountingDate = form.accountingDate, reason = form.reason), review)
}

internal fun ExpenseFactViewModel.keepVoidInput(review: Boolean = false) {
    val form = _uiState.value.voidOffsetForm
    val target = form.target ?: return
    val key = "void:${target.publicId}"
    val baseline = if (review) _uiState.value.expense else factInputSession?.draft(key)?.baseline ?: _uiState.value.expense
    factInputSession?.keep(key, ExpenseFactInputDraft(baseline ?: return, reason = form.reason, voidTarget = target), review)
}

internal fun OffsetFormState.inputKey() = if (kind.isMoneyEvent) "refund" else "reversal"

internal fun ExpenseFactViewModel.restoreVoidInput(target: ExpenseOffsetFact): Boolean {
    val draft = factInputSession?.draft("void:${target.publicId}") ?: return false
    _uiState.update { it.copy(voidOffsetForm = draft.voidForm().copy(open = true)) }
    return true
}

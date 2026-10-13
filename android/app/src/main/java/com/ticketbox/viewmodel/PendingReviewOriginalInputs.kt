package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.ExpenseCommandAcceptance
import com.ticketbox.data.repository.ExpenseFactOriginalInput
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.LocalRepositoryFailure
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

fun PendingViewModel.changeReviewInput(values: PendingReviewValues) {
    val state = _uiState.value
    if (!state.reviewInputReady || state.readOnly || state.reviewInputNeedsReview) return
    val expense = state.activeSheet.reviewExpense() ?: return
    val key = state.activeSheet.reviewInputKey() ?: return
    _uiState.update { it.copy(reviewInputValues = values) }
    reviewInputSession?.keep(key, ExpenseFactInputDraft(expense, pendingReview = values))
}

fun PendingViewModel.retryReviewInput() {
    if (_uiState.value.activeSheet == PendingSheet.None) refreshReviewInputs()
    else if (!_uiState.value.reviewInputReady) loadReviewInput(_uiState.value.activeSheet)
    else reviewInputSession?.retry()
}

fun PendingViewModel.discardReviewInput() {
    val session = reviewInputSession ?: return
    val key = _uiState.value.activeSheet.reviewInputKey() ?: return
    if (session.expenseId in _uiState.value.actionInProgressIds) return
    viewModelScope.launch {
        session.discard(key).onSuccess { if (reviewInputSession === session) closeSheet() }
    }
}

internal fun PendingViewModel.leaveReviewInput(onLeave: () -> Unit) {
    val session = reviewInputSession
    if (session == null) { onLeave(); return }
    viewModelScope.launch {
        val result = session.flush()
        if (reviewInputSession !== session) return@launch
        result.onSuccess { onLeave() }.onFailure { failure ->
            _uiState.update { it.copy(reviewInputError = failure.toUiText(R.string.expense_fact_input_save_failed)) }
        }
    }
}

fun PendingViewModel.resumeReviewInput(task: PendingReviewTask) {
    dismissUndoable()
    reviewSkippedIds.clear()
    loadReviewInput(reviewInputSheet(task.original.formKey, task.expense, task.values))
}

/** Explicitly reading a new basis preserves the human input; submitting remains a separate action. */
fun PendingViewModel.reviewCurrentInputBasis() {
    val state = _uiState.value
    val expense = state.activeSheet.reviewExpense() ?: return
    val key = state.activeSheet.reviewInputKey() ?: return
    val binding = commandBinding() ?: return
    val session = reviewInputSession ?: return
    if (state.readOnly || expense.id in state.actionInProgressIds) return
    _uiState.update { it.copy(reviewInputReady = false) }
    viewModelScope.launch {
        val result = expenseReader.fetchExpense(expense.id, binding)
        if (!holdsCommandBinding(binding) || reviewInputSession !== session) return@launch
        result.onSuccess { latest ->
            if (latest.status != "pending") {
                _uiState.update { it.copy(reviewInputReady = true, reviewInputNeedsReview = true,
                    reviewInputError = UiText.res(R.string.pending_review_input_no_longer_pending)) }
                return@onSuccess
            }
            session.keep(key, ExpenseFactInputDraft(latest, pendingReview = state.reviewInputValues), review = true)
            _uiState.update { it.copy(activeSheet = reviewInputSheet(key, latest, state.reviewInputValues),
                reviewInputReady = true, reviewInputNeedsReview = false,
                message = UiText.res(R.string.pending_review_input_basis_loaded)) }
            if (key == "pending_duplicate") loadDuplicateReference()
        }.onFailure { failure -> _uiState.update { it.copy(reviewInputReady = true,
            reviewInputError = failure.toUiText(R.string.pending_duplicate_reference_failed)) } }
    }
}

internal suspend fun PendingViewModel.admitOriginalReviewInput(
    expense: Expense, submit: suspend (ExpenseFactOriginalInput) -> Result<ExpenseCommandAcceptance>,
): Result<ExpenseCommandAcceptance> {
    val session = reviewInputSession ?: return Result.failure(RepositoryException("",
        localFailure = LocalRepositoryFailure.FactInputNotSaved))
    if (session.expenseId != expense.id) return Result.failure(RepositoryException("",
        localFailure = LocalRepositoryFailure.FactInputNotSaved))
    val key = _uiState.value.activeSheet.reviewInputKey() ?: return Result.failure(RepositoryException("",
        localFailure = LocalRepositoryFailure.FactInputNotSaved))
    session.keep(key, ExpenseFactInputDraft(expense, pendingReview = _uiState.value.reviewInputValues))
    val ready = session.ready(key)
    val original = ready.getOrNull() ?: return Result.failure(requireNotNull(ready.exceptionOrNull()))
    return submit(original).onSuccess {
        session.forget(key)
        refreshReviewInputs()
    }
}


fun PendingViewModel.setDuplicateDecision(confirmed: Boolean) {
    val state = _uiState.value
    val sheet = state.activeSheet as? PendingSheet.Duplicate ?: return
    if (!state.reviewInputReady || state.reviewInputNeedsReview || state.readOnly ||
        sheet.referenceLoading || sheet.expense.id in state.actionInProgressIds) return
    changeReviewInput(_uiState.value.reviewInputValues.copy(confirmed = confirmed))
    _uiState.update { it.copy(activeSheet = sheet.copy(keepBothConfirmed = confirmed)) }
}

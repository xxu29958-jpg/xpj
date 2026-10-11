package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.ExpenseFactOriginalInput
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class PendingReviewTask(val original: ExpenseFactOriginalInput, val expense: Expense, val values: PendingReviewValues)

internal fun PendingSheet.reviewInputKey(): String? = when (this) {
    is PendingSheet.QuickCategory -> "pending_category"
    is PendingSheet.QuickMerchant -> "pending_merchant"
    is PendingSheet.MissingAmount -> "pending_amount"
    is PendingSheet.Duplicate -> "pending_duplicate"
    else -> null
}

internal fun PendingSheet.reviewExpense(): Expense? = when (this) {
    is PendingSheet.QuickCategory -> expense
    is PendingSheet.QuickMerchant -> expense
    is PendingSheet.MissingAmount -> expense
    is PendingSheet.Duplicate -> expense
    else -> null
}

internal fun reviewInputSheet(key: String, expense: Expense, values: PendingReviewValues): PendingSheet = when (key) {
    "pending_category" -> PendingSheet.QuickCategory(expense)
    "pending_merchant" -> PendingSheet.QuickMerchant(expense)
    "pending_amount" -> PendingSheet.MissingAmount(expense)
    "pending_duplicate" -> PendingSheet.Duplicate(expense, keepBothConfirmed = values.confirmed)
    else -> error("Unrecognized review input")
}

internal fun PendingViewModel.loadReviewInput(sheet: PendingSheet) {
    val expense = sheet.reviewExpense() ?: return
    val key = sheet.reviewInputKey() ?: return
    val binding = commandBinding() ?: return
    val generation = ++reviewInputGeneration
    val previous = reviewInputSession
    val previousState = _uiState.value
    _uiState.update { it.copy(activeSheet = sheet, reviewInputReady = false, reviewInputError = null,
        reviewInputValues = PendingReviewValues(), reviewInputNeedsReview = false) }
    viewModelScope.launch(start = CoroutineStart.UNDISPATCHED) {
        val persisted = previous?.flush()
        if (persisted?.isFailure == true) {
            if (generation == reviewInputGeneration) _uiState.update { it.copy(
                activeSheet = previousState.activeSheet, reviewInputReady = previousState.reviewInputReady,
                reviewInputValues = previousState.reviewInputValues, reviewInputNeedsReview = previousState.reviewInputNeedsReview,
                reviewInputError = persisted.exceptionOrNull()?.toUiText(R.string.expense_fact_input_save_failed)) }
            return@launch
        }
        val result = repository.originalInputs.loadFactInputs(binding, expense.id)
        if (!holdsCommandBinding(binding) || generation != reviewInputGeneration) return@launch
        result.onSuccess { originals ->
            try {
                restoreReviewInput(binding, expense, key, originals)
            } catch (_: IllegalArgumentException) {
                _uiState.update { it.copy(reviewInputError = UiText.res(R.string.expense_fact_input_load_failed)) }
            } catch (_: com.squareup.moshi.JsonDataException) {
                _uiState.update { it.copy(reviewInputError = UiText.res(R.string.expense_fact_input_load_failed)) }
            } catch (_: com.squareup.moshi.JsonEncodingException) {
                _uiState.update { it.copy(reviewInputError = UiText.res(R.string.expense_fact_input_load_failed)) }
            }
        }.onFailure { failure ->
            _uiState.update { it.copy(reviewInputError = failure.toUiText(R.string.expense_fact_input_load_failed)) }
        }
    }
}

private fun PendingViewModel.publishReviewInputStatus(session: ExpenseFactInputSession) {
    val inputs = session.keys.mapNotNull { key ->
        val original = session.original(key) ?: return@mapNotNull null
        val draft = session.draft(key) ?: return@mapNotNull null
        draft.pendingReview?.let { PendingReviewTask(original, draft.baseline, it) }
    }
    _uiState.update { state -> state.copy(reviewInputWriting = session.writing,
        reviewInputError = session.error?.toUiText(R.string.expense_fact_input_save_failed),
        reviewTasks = state.reviewTasks.filterNot { it.expense.id == session.expenseId } + inputs) }
}

internal fun PendingViewModel.refreshReviewInputs() {
    val binding = commandBinding() ?: return
    viewModelScope.launch {
        val result = repository.originalInputs.loadPendingReviewInputs(binding)
        if (!holdsCommandBinding(binding)) return@launch
        result.onSuccess { originals ->
            try {
                val tasks = originals.map { original ->
                    val draft = ExpenseFactInputCodec.decode(original.json, original.expenseId)
                    PendingReviewTask(original, draft.baseline, requireNotNull(draft.pendingReview))
                }
                _uiState.update { it.copy(reviewTasks = tasks,
                    reviewInputError = if (it.activeSheet == PendingSheet.None) null else it.reviewInputError) }
                reviewInputSession?.let { publishReviewInputStatus(it) }
            } catch (_: IllegalArgumentException) {
                _uiState.update { it.copy(reviewInputError = UiText.res(R.string.expense_fact_input_load_failed)) }
            } catch (_: com.squareup.moshi.JsonDataException) {
                _uiState.update { it.copy(reviewInputError = UiText.res(R.string.expense_fact_input_load_failed)) }
            } catch (_: com.squareup.moshi.JsonEncodingException) {
                _uiState.update { it.copy(reviewInputError = UiText.res(R.string.expense_fact_input_load_failed)) }
            }
        }.onFailure { failure -> _uiState.update { it.copy(reviewInputError = failure.toUiText(R.string.expense_fact_input_load_failed)) } }
    }
}

private fun PendingViewModel.restoreReviewInput(binding: LogicalSessionBinding, expense: Expense, key: String,
    originals: List<ExpenseFactOriginalInput>) {
    val inputs = originals.filter { it.formKey.startsWith("pending_") }
    inputs.forEach { ExpenseFactInputCodec.decode(it.json, expense.id) }
    lateinit var session: ExpenseFactInputSession
    session = ExpenseFactInputSession(binding, expense.id, repository.originalInputs, viewModelScope, inputs) {
        if (reviewInputSession === session) publishReviewInputStatus(session)
    }
    reviewInputSession = session
    val draft = session.draft(key)
    val values = draft?.pendingReview ?: PendingReviewValues()
    val original = session.original(key)
    _uiState.update { it.copy(activeSheet = reviewInputSheet(key, draft?.baseline ?: expense, values),
        reviewInputValues = values, reviewInputReady = true,
        reviewInputNeedsReview = original != null && original.binding != binding) }
    publishReviewInputStatus(session)
    if (key == "pending_duplicate") loadDuplicateReference()
}

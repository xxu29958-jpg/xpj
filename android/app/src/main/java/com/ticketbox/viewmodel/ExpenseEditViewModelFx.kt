package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.BackgroundTask
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.pendingNeedsFx
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class ExpenseFxUiState(
    val task: BackgroundTask? = null,
    val loading: Boolean = false,
    val message: UiText? = null,
)

fun ExpenseEditViewModel.refreshFx() = requestExpenseFx(retry = false)

fun ExpenseEditViewModel.retryFx() = requestExpenseFx(retry = true)

private fun ExpenseEditViewModel.requestExpenseFx(retry: Boolean) {
    val state = uiState.value
    val expense = state.expense ?: return
    if (state.fx.loading || state.saving || expense.id <= 0) return
    val binding = fxBinding ?: run {
        _uiState.update { it.copy(fx = it.fx.copy(message = UiText.res(R.string.expense_fx_binding_changed))) }
        return
    }
    if (retry && (!pendingNeedsFx(expense) || !repository.canModifyLedger() || state.commandRowIds.isNotEmpty())) return
    _uiState.update { it.copy(fx = it.fx.copy(loading = true, message = null)) }
    viewModelScope.launch {
        val result = if (retry) repository.retryExpenseFx(binding, expense) else repository.fetchExpenseFx(binding, expense.id)
        result.onSuccess { task ->
            _uiState.update { it.copy(fx = ExpenseFxUiState(task = task)) }
        }.onFailure { error ->
            _uiState.update { it.copy(fx = it.fx.copy(
                task = it.fx.task.takeUnless { !retry && error.isReadAccessDenied() },
                loading = false, message = error.toUiText(R.string.expense_fx_read_failed))) }
        }
    }
}

/** Only an explicit review action may replace the editor's original OCC snapshot. */
fun ExpenseEditViewModel.loadFxReview(preserveDraft: Boolean) {
    val started = fxReviewStart(preserveDraft) ?: return
    _uiState.update { it.copy(expenseLoading = true, fx = it.fx.copy(loading = true, message = null)) }
    viewModelScope.launch {
        runCatching {
            // Query Room again: a cached observation can precede admission or an explicit Drop.
            val originals = repository.observeExpenseCommands().first()
            if (originals.access?.binding != started.first) throw CorrectionValidationError(R.string.expense_fx_binding_changed)
            if (originals.commands.any { it.row.targetId == "expense:${started.second.id}" &&
                    it.row.status != PendingMutationStatus.Done }) {
                throw CorrectionValidationError(R.string.expense_command_needs_attention)
            }
            repository.fetchExpenseForFxReview(started.first, started.second.id).getOrThrow()
        }.mapCatching { fresh ->
            applyFxReview(started.first, fresh)
        }.onFailure { error ->
            failFxReview(error)
        }
    }
}

private fun ExpenseEditViewModel.fxReviewStart(preserveDraft: Boolean): Pair<LogicalSessionBinding, Expense>? {
    val state = uiState.value
    val expense = state.expense ?: return null
    val binding = fxBinding ?: run {
        publishFxReviewMessage(R.string.expense_fx_binding_changed)
        return null
    }
    if (fxReviewIsBusy(state)) return null
    if (preserveDraft || state.itemEditorOpen || state.splitEditorOpen) {
        publishFxReviewMessage(R.string.expense_fx_save_draft_first)
        return null
    }
    return binding to expense
}

private fun fxReviewIsBusy(state: ExpenseEditUiState) =
    state.fx.loading || state.expenseLoading || state.itemsLoading || state.splitsLoading ||
        state.saving || state.itemsSaving || state.splitsSaving

private fun ExpenseEditViewModel.publishFxReviewMessage(message: Int) {
    _uiState.update { it.copy(fx = it.fx.copy(message = UiText.res(message))) }
}

private fun ExpenseEditViewModel.failFxReview(error: Throwable) {
    if (error is CancellationException) throw error
    _uiState.update {
        it.copy(expenseLoading = false, fx = it.fx.copy(
            task = it.fx.task.takeUnless { error.isReadAccessDenied() },
            loading = false, message = error.toUiText(R.string.expense_fx_read_failed)))
    }
}

private suspend fun ExpenseEditViewModel.applyFxReview(binding: LogicalSessionBinding, fresh: Expense) {
    val editing = fresh.status != "confirmed"
    val detailsLoadState = if (editing) ExpenseDetailDataLoadState.Loaded else ExpenseDetailDataLoadState.Unknown
    val items = if (editing) repository.fetchExpenseItems(fresh.id).getOrThrow() else null
    val splits = if (editing) repository.fetchExpenseSplits(fresh.id).getOrThrow() else null
    val matchingItems = items == null || (items.expenseId == fresh.id && items.parentRowVersion == fresh.rowVersion)
    val matchingSplits = splits == null || (splits.expenseId == fresh.id && splits.parentRowVersion == fresh.rowVersion)
    val failure = when {
        binding != repository.captureDeferredLedgerBinding() -> UiText.res(R.string.expense_fx_binding_changed)
        !matchingItems || !matchingSplits -> UiText.res(R.string.expense_fx_read_failed)
        else -> null
    }
    if (failure == null) {
        savedState.remove<LongArray>("expense_command_ids")
        savedState.remove<String>("expense_command_binding")
    }
    _uiState.update {
        if (failure != null) {
            it.copy(expenseLoading = false, fx = it.fx.copy(loading = false, message = failure))
        } else {
            it.copy(
                expense = fresh,
                formRevision = it.formRevision + 1,
                preservedFormTimestamp = null,
                originalBaselineRequired = false,
                commandRowIds = emptyList(),
                commandsCompleted = false,
                message = null,
                messageTone = MessageTone.Neutral,
                expenseLoading = false,
                expenseItems = items,
                expenseSplits = splits,
                itemsLoadState = detailsLoadState,
                splitsLoadState = detailsLoadState,
                itemsMessage = null,
                splitsMessage = null,
                itemsMessageTone = MessageTone.Neutral,
                splitsMessageTone = MessageTone.Neutral,
                fx = ExpenseFxUiState(task = fresh.fxTask),
            )
        }
    }
}

package com.ticketbox.viewmodel

import androidx.annotation.StringRes
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.ExpenseCommandAcceptance
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.PendingExpenseCommand
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** One submission keeps the original rows; completion never replaces a user's current raw form. */
internal fun ExpenseEditViewModel.submitExpenseCommand(
    @StringRes failureMessage: Int,
    submit: suspend (LogicalSessionBinding, Expense) -> Result<ExpenseCommandAcceptance>,
) {
    val state = uiState.value
    if (state.saving || state.ocrRunning) return
    val binding = fxBinding
    val refusal = expenseSubmissionRefusal(state, binding)
    if (refusal != null) {
        _uiState.update {
            it.copy(
                readOnly = !repository.canModifyLedger() || it.readOnly,
                message = UiText.res(refusal),
                messageTone = MessageTone.Danger,
            )
        }
        return
    }
    val expense = requireNotNull(state.expense)
    val captured = requireNotNull(binding)
    _uiState.update { it.copy(saving = true, message = null, recognizeTextDialogOpen = false) }
    viewModelScope.launch {
        submit(captured, expense).onSuccess { accepted ->
            if (repository.captureDeferredLedgerBinding() != captured) return@onSuccess
            _uiState.update { it.copy(expense = accepted.expense, saving = false, ocrRunning = false,
                commandRowIds = accepted.rowIds, commandsCompleted = false, done = false,
                doneAdviceInputsChanged = false, message = UiText.res(R.string.expense_command_accepted),
                messageTone = MessageTone.Info) }
            reconcileExpenseCommands()
        }.onFailure { error ->
            if (repository.captureDeferredLedgerBinding() != captured) return@onFailure
            _uiState.update { it.copy(saving = false, ocrRunning = false,
                message = error.toUiText(failureMessage), messageTone = MessageTone.Danger) }
        }
    }
}

private fun ExpenseEditViewModel.expenseSubmissionRefusal(state: ExpenseEditUiState, binding: LogicalSessionBinding?): Int? = when {
        !repository.canModifyLedger() -> R.string.common_readonly_ledger
        binding == null || binding != repository.captureDeferredLedgerBinding() -> R.string.expense_fx_binding_changed
        state.expense == null -> R.string.expense_edit_page_not_loaded
        state.originalBaselineRequired -> R.string.original_edit_baseline
        state.commandRowIds.isNotEmpty() -> if (state.commandsCompleted) {
            R.string.expense_command_completed
        } else R.string.expense_command_needs_attention
        else -> null
    }

internal fun ExpenseEditViewModel.observeExpenseCommands() {
    viewModelScope.launch {
        repository.observeExpenseCommands().collect { observation ->
            commandObservation = observation
            if (observation.access?.binding != fxBinding) {
                _uiState.update { it.copy(readOnly = true, saving = false, ocrRunning = false,
                    message = UiText.res(R.string.expense_fx_binding_changed), messageTone = MessageTone.Danger) }
            } else {
                _uiState.update { it.copy(readOnly = observation.access?.canModify != true) }
                reconcileExpenseCommands()
            }
        }
    }
}

internal fun ExpenseEditViewModel.reconcileExpenseCommands() {
    val observation = commandObservation ?: return
    if (observation.access?.binding != fxBinding || repository.captureDeferredLedgerBinding() != fxBinding) return
    val ids = uiState.value.commandRowIds
    if (ids.isEmpty()) return
    applyExpenseCommandProgress(observation.commands.filter { it.row.id in ids }, ids)
}

private fun ExpenseEditViewModel.applyExpenseCommandProgress(
    originals: List<PendingExpenseCommand>,
    ids: List<Long>,
) {
    val progress = expenseCommandProgress(originals, ids)
    _uiState.update {
        it.copy(
            commandsCompleted = progress.complete,
            done = it.done || progress.leavesEditor,
            doneAdviceInputsChanged = it.doneAdviceInputsChanged || progress.confirmed,
            message = UiText.res(progress.message),
            messageTone = if (progress.failed) MessageTone.Danger else MessageTone.Info,
        )
    }
}

private data class ExpenseCommandProgress(
    val complete: Boolean,
    val failed: Boolean,
    val leavesEditor: Boolean,
    val confirmed: Boolean,
    @StringRes val message: Int,
)

private fun expenseCommandProgress(originals: List<PendingExpenseCommand>, ids: List<Long>): ExpenseCommandProgress {
    val complete = originals.size == ids.size && originals.all { it.row.status == PendingMutationStatus.Done }
    val failed = originals.any { it.row.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict) }
    return ExpenseCommandProgress(
        complete = complete,
        failed = failed,
        leavesEditor = complete && originals.any {
            it.row.type == PendingMutationType.ConfirmExpense || it.row.type == PendingMutationType.RejectExpense
        },
        confirmed = complete && originals.any { it.row.type == PendingMutationType.ConfirmExpense },
        message = when {
            complete -> R.string.expense_command_completed
            failed -> R.string.expense_command_needs_attention
            else -> R.string.expense_command_accepted
        },
    )
}

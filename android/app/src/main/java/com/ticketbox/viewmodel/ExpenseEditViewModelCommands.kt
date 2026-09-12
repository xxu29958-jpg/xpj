package com.ticketbox.viewmodel

import androidx.annotation.StringRes
import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.ExpenseCommandAcceptance
import com.ticketbox.data.repository.LogicalSessionBinding
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
    val refusal = when {
        !repository.canModifyLedger() -> R.string.common_readonly_ledger
        binding == null || binding != repository.captureDeferredLedgerBinding() -> R.string.expense_fx_binding_changed
        state.expense == null -> R.string.expense_edit_page_not_loaded
        state.commandRowIds.isNotEmpty() -> if (state.commandsCompleted) {
            R.string.expense_command_completed
        } else R.string.expense_command_needs_attention
        else -> null
    }
    if (refusal != null) {
        _uiState.update { it.copy(message = UiText.res(refusal), messageTone = MessageTone.Danger) }
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
    val originals = observation.commands.filter { it.row.id in ids }
    val complete = originals.size == ids.size && originals.all { it.row.status == PendingMutationStatus.Done }
    val failed = originals.any { it.row.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict) }
    _uiState.update { it.copy(commandsCompleted = complete,
        message = UiText.res(when {
            complete -> R.string.expense_command_completed
            failed -> R.string.expense_command_needs_attention
            else -> R.string.expense_command_accepted
        }), messageTone = if (failed) MessageTone.Danger else MessageTone.Info) }
}

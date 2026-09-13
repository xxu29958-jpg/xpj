package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.ExpenseCommandAcceptance
import com.ticketbox.data.repository.PendingExpenseCommand
import com.ticketbox.data.repository.expenseOutboxTargetId
import com.ticketbox.data.repository.expenseRefreshTargetId
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.flow.update

/** Local acceptance retains the reviewed fields; only the original command can publish its outcome. */
internal fun PendingViewModel.acceptExpenseCommand(accepted: ExpenseCommandAcceptance, offerUndo: Boolean = true) {
    commandRowsByExpense[accepted.expense.id] = accepted.rowIds.toSet()
    if (!offerUndo) ignoredRejectRows.addAll(accepted.rowIds)
    _uiState.update {
        PendingUiStateReducer.afterUpdated(it, accepted.expense, closeSheet = false,
            message = UiText.res(R.string.expense_command_accepted), clearInProgress = false)
    }
    reconcileExpenseCommands()
}

internal fun PendingViewModel.reconcileExpenseCommands() {
    val observation = commandObservation ?: return
    if (observation.access?.binding == null || observation.access.binding != currentUploadBinding()) return
    val commands = observation.commands
    val completed = commands.filter { it.row.status == PendingMutationStatus.Done && seenCommandCompletions.add(it.row.id) }
    completed.forEach { adoptPendingCommand(it) }
    val byId = commands.associateBy { it.row.id }
    if (bulkCommandRows.isNotEmpty()) _uiState.update { state ->
        state.copy(bulkConfirm = state.bulkConfirm.copy(
            succeeded = bulkCommandRows.count { byId[it]?.row?.status == PendingMutationStatus.Done },
            failed = bulkCommandRows.count { byId[it]?.row?.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict) }))
    }
    val finished = commandRowsByExpense.filterValues { ids ->
        ids.isNotEmpty() && ids.all { byId[it]?.row?.status == PendingMutationStatus.Done }
    }.keys.toList()
    finished.forEach { commandRowsByExpense.remove(it) }
    if (finished.isNotEmpty()) _uiState.update {
        it.copy(actionInProgressIds = it.actionInProgressIds - finished.toSet(),
            message = UiText.res(R.string.expense_command_completed))
    }
    val needsAttention = commandRowsByExpense.values.flatten().any {
        byId[it]?.row?.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict)
    }
    if (needsAttention) _uiState.update { it.copy(message = UiText.res(R.string.expense_command_needs_attention)) }
    if (completed.isNotEmpty()) {
        recomputeReviewRemaining()
        onDataChanged()
        if (completed.any { it.row.type == PendingMutationType.ConfirmExpense ||
                (it.row.type == PendingMutationType.UndoExpense && it.acceptedExpense?.status == "confirmed") }) {
            onAdviceInputsChanged()
        }
        if (completed.any { it.row.type != PendingMutationType.UndoExpense }) refresh(clearMessage = false)
    }
}

private fun PendingViewModel.adoptPendingCommand(command: PendingExpenseCommand) {
    val row = command.row
    val accepted = command.acceptedExpense
    val expenseId = expenseRefreshTargetId(row.targetId, row.receiptJson)
    when (row.type) {
        PendingMutationType.ConfirmExpense -> _uiState.update { state ->
            state.copy(items = state.items.filterNot { it.id == expenseId || expenseOutboxTargetId(it) == row.targetId })
        }
        PendingMutationType.RejectExpense -> if (accepted?.status == "rejected") {
            _uiState.update { state ->
                val updated = PendingUiStateReducer.afterRejected(state, accepted, message = UiText.res(R.string.pending_msg_rejected))
                if (row.id in ignoredRejectRows || state.readOnly) updated else updated.copy(undoableExpense = accepted)
            }
            if (_uiState.value.undoableExpense == accepted) startUndoTimer(accepted.id)
        }
        PendingMutationType.UndoExpense -> if (accepted != null) {
            refreshSkipEpoch += 1
            _uiState.update { state ->
                val others = state.items.filterNot { it.id == accepted.id }
                state.copy(items = if (accepted.status == "pending") listOf(accepted) + others else others,
                    message = UiText.res(R.string.pending_msg_undo_restored))
            }
        }
        else -> Unit
    }
}

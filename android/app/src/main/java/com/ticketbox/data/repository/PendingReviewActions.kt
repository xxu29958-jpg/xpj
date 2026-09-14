package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ProtectedImage
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow

/** Pending review admits original commands; only delivered receipts establish completion. */
interface PendingReviewActions {
    fun canModifyLedger(): Boolean = true
    fun observeActiveLedgerId(): Flow<String?> = emptyFlow()
    fun currentActiveLedgerId(): String? = null
    fun observeExpenseCommands(): Flow<ExpenseCommandObservation>
    suspend fun fetchPending(): Result<List<Expense>>
    suspend fun getCachedPending(): Result<List<Expense>>
    fun observeConfirmed(): Flow<List<Expense>>
    suspend fun syncPending(): Result<List<Expense>>
    suspend fun fetchThumbnail(id: Long): Result<ProtectedImage>
    suspend fun categories(): Result<List<String>>

    suspend fun saveExpenseAllowingOffline(
        expectedBinding: LogicalSessionBinding, id: Long, draft: ExpenseDraft, baseline: Expense,
    ): Result<ExpenseCommandAcceptance>
    suspend fun saveAndConfirmExpense(
        expectedBinding: LogicalSessionBinding, expense: Expense, draft: ExpenseDraft,
    ): Result<ExpenseCommandAcceptance>
    suspend fun confirmExpenses(
        expectedBinding: LogicalSessionBinding, expenses: List<Expense>,
    ): Result<List<ExpenseCommandAcceptance>>
    suspend fun confirmExpenseAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance>
    suspend fun rejectExpenseAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance>
    suspend fun markNotDuplicateAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance>
    suspend fun undoRejectExpense(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance>
}

/** Local acceptance carries a draft projection, never an invented server status or row version. */
data class ExpenseCommandAcceptance(val expense: Expense, val rowIds: List<Long>)

data class ExpenseCommandObservation(val access: LedgerAccessContext?, val commands: List<PendingExpenseCommand>)

/** Rejection/undo retain the original snapshot; other commands need only the original row. */
data class PendingExpenseCommand(val row: OutboxRow, val acceptedExpense: Expense?)

internal val PENDING_EXPENSE_COMMAND_TYPES = setOf(
    PendingMutationType.PatchExpense, PendingMutationType.ConfirmExpense, PendingMutationType.RejectExpense,
    PendingMutationType.UndoExpense, PendingMutationType.MarkNotDuplicate, PendingMutationType.RetryOcr,
    PendingMutationType.RecognizeText,
)

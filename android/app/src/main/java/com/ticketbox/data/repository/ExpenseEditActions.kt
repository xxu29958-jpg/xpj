package com.ticketbox.data.repository

import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ExpenseItemDraft
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplitDraft
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.ProtectedImage

/** Actions consumed by the pending editor and its existing item/split editors. */
interface ExpenseEditActions {
    fun canModifyLedger(): Boolean = true
    fun captureDeferredLedgerBinding(): LogicalSessionBinding?
    suspend fun fetchExpenseFx(binding: LogicalSessionBinding, id: Long): Result<com.ticketbox.domain.model.BackgroundTask?>
    suspend fun retryExpenseFx(binding: LogicalSessionBinding, expense: Expense): Result<com.ticketbox.domain.model.BackgroundTask>
    suspend fun fetchExpenseForFxReview(binding: LogicalSessionBinding, id: Long): Result<Expense>
    suspend fun fetchExpense(id: Long): Result<Expense>

    /**
     * issue #65 slice 5: load a not-yet-synced offline-create row (NEGATIVE local
     * id) from the local cache — the server can't resolve a negative id, so
     * [fetchExpense] would 404. Defaults to [fetchExpense] so an implementer that
     * doesn't cache keeps the pre-slice-5 behaviour (the server error surfaces as
     * a load failure); the real repository overrides it.
     */
    suspend fun fetchExpenseFromLocalCache(id: Long): Result<Expense> = fetchExpense(id)
    suspend fun categories(): Result<List<String>>
    suspend fun fetchThumbnail(id: Long): Result<ProtectedImage>
    suspend fun fetchImage(id: Long): Result<ProtectedImage>

    fun observeExpenseCommands(): kotlinx.coroutines.flow.Flow<ExpenseCommandObservation>
    suspend fun saveExpenseAllowingOffline(
        expectedBinding: LogicalSessionBinding, id: Long, draft: ExpenseDraft, baseline: Expense,
    ): Result<ExpenseCommandAcceptance>
    suspend fun saveAndConfirmExpense(
        expectedBinding: LogicalSessionBinding, expense: Expense, draft: ExpenseDraft,
    ): Result<ExpenseCommandAcceptance>
    suspend fun confirmExpenseAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance>
    suspend fun rejectExpenseAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance>
    suspend fun retryOcrAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance>
    suspend fun recognizeTextAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense, rawText: String,
    ): Result<ExpenseCommandAcceptance>
    suspend fun markNotDuplicateAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance>
    suspend fun fetchExpenseItems(id: Long): Result<ExpenseItems>
    suspend fun acknowledgeItemsMismatchAllowingOffline(
        expense: Expense,
        currentItems: ExpenseItems,
    ): Result<ItemsAckOutcome>

    suspend fun replaceExpenseItemsAllowingOffline(
        expense: Expense,
        items: List<ExpenseItemDraft>,
        currentItems: ExpenseItems,
    ): Result<ReplaceItemsOutcome>

    suspend fun fetchExpenseSplits(id: Long): Result<ExpenseSplits>
    suspend fun fetchSplitMembers(): Result<List<FamilyMember>>
    suspend fun replaceExpenseSplitsAllowingOffline(
        expense: Expense,
        splits: List<ExpenseSplitDraft>,
        currentSplits: ExpenseSplits,
    ): Result<ReplaceSplitsOutcome>

}

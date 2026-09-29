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
interface ExpenseEditActions : ExpenseRootReadActions {
    val readAccessDenials: kotlinx.coroutines.flow.Flow<SnapshotAccessDenial> get() = kotlinx.coroutines.flow.emptyFlow()
    fun canModifyLedger(): Boolean = true
    fun captureDeferredLedgerBinding(): LogicalSessionBinding?
    suspend fun fetchExpenseFx(binding: LogicalSessionBinding, id: Long): Result<com.ticketbox.domain.model.BackgroundTask?>
    suspend fun retryExpenseFx(binding: LogicalSessionBinding, expense: Expense): Result<com.ticketbox.domain.model.BackgroundTask>
    suspend fun fetchExpenseForFxReview(binding: LogicalSessionBinding, id: Long): Result<Expense>

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

package com.ticketbox.data.repository

import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseCorrectionOutcome
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseRevisionPage
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.RepaymentDraft

/** Read side of the confirmed-fact consumer; pending editing is intentionally absent. */
interface ExpenseFactReadActions {
    /** Existing client timezone owner used by every ledger query/command. */
    fun currentTimezoneId(): String
    suspend fun fetchExpense(id: Long): Result<Expense>
    suspend fun fetchExpenseFromLocalCache(id: Long): Result<Expense>
    suspend fun categories(): Result<List<String>>
    suspend fun fetchThumbnail(id: Long): Result<ProtectedImage>
    suspend fun fetchImage(id: Long): Result<ProtectedImage>
    suspend fun fetchExpenseItems(id: Long): Result<ExpenseItems>
    suspend fun fetchExpenseSplits(id: Long): Result<ExpenseSplits>
    suspend fun fetchSplitMembers(): Result<List<FamilyMember>>
    suspend fun fetchExpenseRevisions(
        id: Long,
        page: Int = 1,
        pageSize: Int = 50,
    ): Result<ExpenseRevisionPage>
}

/** Commands reachable from the confirmed-fact surface. */
interface ExpenseFactCommandActions {
    fun canModifyLedger(): Boolean
    suspend fun correctExpenseAllowingOffline(
        expense: Expense,
        correction: ExpenseCorrectionDraft,
    ): Result<ExpenseCorrectionOutcome>
    suspend fun createRepaymentDraftFromExpense(expense: Expense): Result<RepaymentDraft>
    suspend fun createBillSplitInvitation(
        expenseId: Long,
        receiverAccountId: Long,
        amountCents: Long,
    ): Result<BillSplitSent>
    suspend fun fetchBillSplitSent(): Result<List<BillSplitSent>>
    suspend fun cancelBillSplitInvitation(publicId: String): Result<BillSplitSent>
}

/** Page-level port composed from independently bounded read and command responsibilities. */
interface ExpenseFactActions : ExpenseFactReadActions, ExpenseFactCommandActions

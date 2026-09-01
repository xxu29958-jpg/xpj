package com.ticketbox.data.repository

import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseCorrectionOutcome
import com.ticketbox.domain.model.ExpenseFactBundle
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseRevisionPage
import com.ticketbox.domain.model.ExpenseOffsetDraft
import com.ticketbox.domain.model.ExpenseOffsetFact
import com.ticketbox.domain.model.ExpenseOffsetMutationOutcome
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
        /** null = 进入新服务端快照；翻页必须回传已保存的锚。 */
        snapshotRevision: Long? = null,
    ): Result<ExpenseRevisionPage>
    suspend fun fetchExpenseFactBundle(id: Long): Result<ExpenseFactBundle>
}

/** Commands reachable from the confirmed-fact surface. */
interface ExpenseFactCommandActions {
    fun canModifyLedger(): Boolean
    suspend fun correctExpenseAllowingOffline(
        expense: Expense,
        correction: ExpenseCorrectionDraft,
    ): Result<ExpenseCorrectionOutcome>
    suspend fun createExpenseOffsetAllowingOffline(
        expense: Expense,
        draft: ExpenseOffsetDraft,
    ): Result<ExpenseOffsetMutationOutcome>
    suspend fun voidExpenseOffsetAllowingOffline(
        expense: Expense,
        offset: ExpenseOffsetFact,
        reason: String,
    ): Result<ExpenseOffsetMutationOutcome>

    /**
     * 「原小票如此」明细差异确认：不是字段编辑，而是经既有 OCC/幂等/Outbox
     * owner 的状态确认；[ExpenseRepository] 的既有 override 同时满足本端口。
     */
    suspend fun acknowledgeItemsMismatchAllowingOffline(
        expense: Expense,
        currentItems: ExpenseItems,
    ): Result<ItemsAckOutcome>
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

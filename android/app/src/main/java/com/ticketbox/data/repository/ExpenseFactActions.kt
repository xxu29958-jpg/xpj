package com.ticketbox.data.repository


import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseCorrectionDraft
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
    fun observeCorrections(): kotlinx.coroutines.flow.Flow<ExpenseCorrectionObservation>
    suspend fun submitCorrection(expectedBinding: LogicalSessionBinding, expense: Expense,
        correction: ExpenseCorrectionDraft): Result<Long>
    suspend fun recoverCorrection(expectedBinding: LogicalSessionBinding, rowId: Long, drop: Boolean): Result<Unit>
    suspend fun createExpenseOffsetAllowingOffline(
        expectedBinding: LogicalSessionBinding,
        expense: Expense,
        draft: ExpenseOffsetDraft,
    ): Result<ExpenseOffsetMutationOutcome>
    suspend fun voidExpenseOffsetAllowingOffline(
        expectedBinding: LogicalSessionBinding,
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
    suspend fun createRepaymentDraftFromExpense(
        expectedBinding: LogicalSessionBinding,
        expense: Expense,
    ): Result<RepaymentDraft>

}

/** Page-level port composed from independently bounded read and command responsibilities. */
interface ExpenseFactActions : ExpenseFactReadActions, ExpenseFactCommandActions, BillSplitSourceActions

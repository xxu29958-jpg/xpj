package com.ticketbox.data.repository

import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ExpenseItemDraft
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplitDraft
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.ProtectedImage

/**
 * 架构债 #5：ExpenseEditViewModel 依赖反转用接口。
 *
 * 抽出编辑屏（主编辑面 + items 编辑器 + splits 编辑器）所用到的
 * Repository 方法，便于在单元测试里以 Fake 实现替换
 * [ExpenseRepository]（final 门面，无法直接 fake）——与
 * [PendingReviewActions] / TagActions 同一模式。
 *
 * 注意：仅声明编辑屏必需的方法；其它 Repository 能力仍直接挂在
 * [ExpenseRepository] 上，本接口不负责。与 [PendingReviewActions]
 * 重叠的签名（canModifyLedger / fetchThumbnail / updateExpense /
 * saveExpenseAllowingOffline / confirm·reject·markNotDuplicate
 * AllowingOffline / categories）由 [ExpenseRepository] 的同一个
 * override 同时满足两个接口。
 */
interface ExpenseEditActions {
    fun canModifyLedger(): Boolean = true
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

    /** Direct PATCH only — see [PendingReviewActions.updateExpense] for the
     *  chained-flow rationale. The edit screen only calls this on the
     *  no-baseline fallback path (no OCC token to protect). */
    suspend fun updateExpense(
        id: Long,
        draft: ExpenseDraft,
        baseline: Expense?,
    ): Result<Expense>

    suspend fun saveExpenseAllowingOffline(
        id: Long,
        draft: ExpenseDraft,
        baseline: Expense,
    ): Result<SaveOutcome>

    suspend fun confirmExpenseAllowingOffline(expense: Expense): Result<ExpenseStateOutcome>
    suspend fun rejectExpenseAllowingOffline(expense: Expense): Result<ExpenseStateOutcome>
    suspend fun retryOcrAllowingOffline(expense: Expense): Result<ExpenseStateOutcome>
    suspend fun recognizeTextAllowingOffline(expense: Expense, rawText: String): Result<ExpenseStateOutcome>
    suspend fun markNotDuplicateAllowingOffline(expense: Expense): Result<ExpenseStateOutcome>

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

    // ADR-0029 拆账发起闭环（批 13）：编辑页「找家人分摊」卡 + 发起 sheet 用。
    // 在线-only（无 outbox，无幂等键）：直连失败直接报错，不入离线队列。
    suspend fun createBillSplitInvitation(
        expenseId: Long,
        receiverAccountId: Long,
        amountCents: Long,
    ): Result<BillSplitSent>

    /** 本票已发出的拆账邀请；调用方按 senderExpenseId 客户端过滤出本票的。 */
    suspend fun fetchBillSplitSent(): Result<List<BillSplitSent>>

    /** 撤回一条 invited 状态的拆账邀请（卡内 invited 行的撤回钮复用此动作）。 */
    suspend fun cancelBillSplitInvitation(publicId: String): Result<BillSplitSent>
}

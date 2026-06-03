package com.ticketbox.viewmodel

import com.ticketbox.data.repository.PendingReviewActions
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ProtectedImage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain

/**
 * v0.4-alpha4 M1：PendingViewModel Review Actions 单元测试的共享脚手架。
 *
 * 原 [PendingViewModelReviewActionsTest] 体量过大，按 review action /
 * scenario 拆成多个同包姊妹测试类（QuickEdit / 确认·拒绝·重复 / ADR-0038
 * 撤销 banner / 只读·sheet·reducer·ledger-change）。它们共用的 [review]
 * 计时器卫生 helper、[expense] / [image] 样本构造器都集中在这个
 * [PendingViewModelReviewTestBase] 基类里，[FakeReviewActions] 作为同包
 * 顶层类抽出，避免在各文件之间重复。
 *
 * 通过 [PendingReviewActions] 接口注入 [FakeReviewActions]，验证
 * QuickCategory / QuickMerchant / MissingAmount / BulkConfirm /
 * DuplicateAction 等 review action 的核心契约。
 */
@OptIn(ExperimentalCoroutinesApi::class)
internal abstract class PendingViewModelReviewTestBase {

    protected fun review(block: suspend TestScope.() -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block()
        } finally {
            // ADR-0038 timer hygiene: PendingViewModel's 5s undo timer is a
            // viewModelScope.launch that may be sitting on delay(5_000) when
            // the test body completes. If we resetMain BEFORE draining it,
            // runTest's structured-concurrency teardown will try to cancel
            // it through Dispatchers.Main (now unset) and throw
            // DispatchException → "Dispatchers.Main was accessed when ...
            // test dispatcher was unset". Drain pending work first.
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    protected fun expense(
        id: Long,
        amountCents: Long? = 100L,
        merchant: String? = "Merchant",
        category: String = "其他",
        duplicateStatus: String = "none",
        status: String = "pending",
        originalCurrencyCode: CurrencyCode = CurrencyCode.CNY,
        originalAmountMinor: Long? = amountCents,
        imagePath: String? = null,
    ): Expense = Expense(
        id = id,
        publicId = "pub-$id",
        amountCents = amountCents,
        originalCurrency = originalCurrencyCode,
        originalCurrencyCode = originalCurrencyCode,
        originalAmountMinor = originalAmountMinor,
        merchant = merchant,
        category = category,
        note = null,
        source = "manual",
        imagePath = imagePath,
        thumbnailPath = null,
        imageHash = null,
        rawText = null,
        confidence = null,
        duplicateStatus = duplicateStatus,
        duplicateOfId = null,
        duplicateReason = null,
        tags = null,
        valueScore = null,
        regretScore = null,
        status = status,
        expenseTime = null,
        createdAt = "2025-01-01T00:00:00Z",
        updatedAt = "2025-01-01T00:00:00Z",
        rowVersion = 1L,
        confirmedAt = null,
        rejectedAt = null,
    )

    protected fun image(label: String): ProtectedImage =
        ProtectedImage(bytes = label.encodeToByteArray(), contentType = "image/jpeg")
}

internal class FakeReviewActions(
    pending: List<Expense> = emptyList(),
    private val categoryOptions: List<String> = listOf("餐饮", "交通", "购物"),
    canModifyLedger: Boolean = true,
    private val activeLedgerFlow: Flow<String?> = emptyFlow(),
    private val activeLedgerIdProvider: () -> String? = { null },
) : PendingReviewActions {
    // Mutable so tests can simulate backend role demotion mid-flow (V11):
    // the existing canModifyLedger = false ctor arg still works for
    // "viewer from the start" scenarios.
    var canModifyLedgerFlag: Boolean = canModifyLedger

    var pending: List<Expense> = pending

    var updateResponder: (suspend (Long, ExpenseDraft) -> Result<Expense>)? = null
    var confirmResponder: (suspend (Long) -> Result<Expense>)? = null
    var rejectResponder: (suspend (Long) -> Result<Expense>)? = null
    // ADR-0038 undo: drives [PendingReviewActions.undoRejectExpense].
    var undoRejectResponder: (suspend (Long) -> Result<Expense>)? = null
    var markNotDuplicateResponder: (suspend (Long) -> Result<Expense>)? = null
    // PR-2g.7: offline-aware confirm/reject. Default to wrapping the
    // existing confirm/rejectResponder in a Synced outcome so the
    // online-path tests keep passing unchanged; set these to drive
    // the Queued (offline) branch.
    var confirmOfflineResponder: (suspend (Long) -> Result<com.ticketbox.data.repository.ExpenseStateOutcome>)? = null
    var rejectOfflineResponder: (suspend (Long) -> Result<com.ticketbox.data.repository.ExpenseStateOutcome>)? = null
    // PR-2g.8: same default-wrap pattern for mark-not-duplicate.
    var markNotDuplicateOfflineResponder: (suspend (Long) -> Result<com.ticketbox.data.repository.ExpenseStateOutcome>)? = null
    var fetchPendingResponder: (suspend () -> Result<List<Expense>>)? = null
    var thumbnailResponder: (suspend (Long) -> Result<ProtectedImage>)? = null

    var updateCalls: Int = 0
        private set
    var confirmCalls: Int = 0
        private set
    var rejectCalls: Int = 0
        private set
    var markNotDuplicateCalls: Int = 0
        private set
    var uploadCalls: Int = 0
        private set
    var fetchPendingCalls: Int = 0
        private set
    val confirmedIds = mutableListOf<Long>()

    override fun canModifyLedger(): Boolean = canModifyLedgerFlag

    override fun observeActiveLedgerId(): Flow<String?> = activeLedgerFlow

    override fun currentActiveLedgerId(): String? = activeLedgerIdProvider()

    override suspend fun fetchPending(): Result<List<Expense>> {
        fetchPendingCalls += 1
        fetchPendingResponder?.let { return it() }
        return Result.success(pending)
    }

    override suspend fun fetchThumbnail(id: Long): Result<ProtectedImage> =
        thumbnailResponder?.invoke(id)
            ?: Result.failure(IllegalStateException("no thumbnail in tests"))

    override suspend fun updateExpense(id: Long, draft: ExpenseDraft, baseline: Expense?): Result<Expense> {
        updateCalls += 1
        return updateResponder?.invoke(id, draft)
            ?: error("updateResponder not set; got id=$id draft=$draft baseline=$baseline")
    }

    override suspend fun saveExpenseAllowingOffline(
        id: Long,
        draft: ExpenseDraft,
        baseline: Expense,
    ): Result<com.ticketbox.data.repository.SaveOutcome> =
        Result.failure(IllegalStateException("not exercised — PendingViewModel uses updateExpense"))

    override suspend fun confirmExpense(id: Long, expectedRowVersion: Long): Result<Expense> {
        confirmCalls += 1
        confirmedIds += id
        return confirmResponder?.invoke(id)
            ?: error("confirmResponder not set; got id=$id token=$expectedRowVersion")
    }

    override suspend fun rejectExpense(id: Long, expectedRowVersion: Long): Result<Expense> {
        rejectCalls += 1
        return rejectResponder?.invoke(id) ?: error("rejectResponder not set")
    }

    override suspend fun confirmExpenseAllowingOffline(
        expense: Expense,
    ): Result<com.ticketbox.data.repository.ExpenseStateOutcome> {
        confirmCalls += 1
        confirmedIds += expense.id
        confirmOfflineResponder?.let { return it(expense.id) }
        return confirmResponder?.invoke(expense.id)
            ?.map { com.ticketbox.data.repository.ExpenseStateOutcome.Synced(it) }
            ?: error("confirmResponder/confirmOfflineResponder not set; got id=${expense.id}")
    }

    override suspend fun rejectExpenseAllowingOffline(
        expense: Expense,
    ): Result<com.ticketbox.data.repository.ExpenseStateOutcome> {
        rejectCalls += 1
        rejectOfflineResponder?.let { return it(expense.id) }
        // Sweep #2 fix: the real backend POST /reject returns the row with
        // status='rejected' (and rejectedAt populated); the default wrap
        // here used to leak the caller's factory-default 'pending' status,
        // making any ViewModel test that reads
        // `undoableExpense.status == "rejected"` (e.g. the undo-banner
        // contract) silently pass against an unrealistic shape. Match the
        // explicit Queued branch in [rejectQueuedOfflineRemovesItem...] —
        // both branches now project the same post-transition shape.
        return rejectResponder?.invoke(expense.id)
            ?.map { restored ->
                com.ticketbox.data.repository.ExpenseStateOutcome.Synced(
                    restored.copy(status = "rejected"),
                ) as com.ticketbox.data.repository.ExpenseStateOutcome
            }
            ?: error("rejectResponder/rejectOfflineResponder not set")
    }

    override suspend fun undoRejectExpense(id: Long, expectedRowVersion: Long): Result<Expense> =
        undoRejectResponder?.invoke(id) ?: error("undoRejectResponder not set")

    override suspend fun markNotDuplicate(id: Long, expectedRowVersion: Long): Result<Expense> {
        markNotDuplicateCalls += 1
        return markNotDuplicateResponder?.invoke(id) ?: error("markNotDuplicateResponder not set")
    }

    override suspend fun markNotDuplicateAllowingOffline(
        expense: Expense,
    ): Result<com.ticketbox.data.repository.ExpenseStateOutcome> {
        markNotDuplicateCalls += 1
        markNotDuplicateOfflineResponder?.let { return it(expense.id) }
        return markNotDuplicateResponder?.invoke(expense.id)
            ?.map { com.ticketbox.data.repository.ExpenseStateOutcome.Synced(it) }
            ?: error("markNotDuplicateResponder/markNotDuplicateOfflineResponder not set")
    }

    override suspend fun categories(): Result<List<String>> = Result.success(categoryOptions)

    override suspend fun uploadScreenshot(
        fileName: String,
        contentType: String?,
        bytes: ByteArray,
        preparationDurationMs: Long?,
        sourceSizeBytes: Long?,
        expectedLedgerId: String?,
    ): Result<Long> {
        uploadCalls += 1
        return Result.failure(IllegalStateException("upload not exercised in tests"))
    }
}

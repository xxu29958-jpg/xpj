package com.ticketbox.viewmodel

import androidx.lifecycle.ViewModelStore
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.ExpenseCommandAcceptance
import com.ticketbox.data.repository.ExpenseCommandObservation
import com.ticketbox.data.repository.PendingExpenseCommand
import com.ticketbox.data.repository.PendingReviewActions
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.UploadIntentActions
import com.ticketbox.data.repository.PendingEnrichmentTaskReader
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.PendingEnrichmentOutcome
import com.ticketbox.domain.model.PendingEnrichmentTask
import com.ticketbox.domain.model.ProtectedImage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.emptyFlow
import kotlinx.coroutines.flow.flowOf
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
    private val viewModels = ViewModelStore()
    private var nextViewModel = 0

    protected fun pendingViewModel(
        fake: FakeReviewActions,
        uploadIntents: UploadIntentActions = fake.uploadIntents,
        enrichmentTaskReader: PendingEnrichmentTaskReader? = null,
        onDataChanged: () -> Unit = {},
    ): PendingViewModel = PendingViewModel(
        fake.also { it.commandAccessSource = uploadIntents }, uploadIntents, enrichmentTaskReader = enrichmentTaskReader, onDataChanged = onDataChanged,
    ).also { viewModels.put("pending-${nextViewModel++}", it) }

    protected fun clearPendingViewModels() = viewModels.clear()


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
            viewModels.clear()
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    protected data class PendingExpenseDetails(
        val duplicateStatus: String = "none",
        val status: String = "pending",
        val originalCurrencyCode: CurrencyCode = CurrencyCode.CNY,
        val originalAmountMinor: Long? = null,
        val useAmountAsOriginalMinor: Boolean = true,
        val imagePath: String? = null,
    )

    protected fun expense(
        id: Long,
        amountCents: Long? = 100L,
        merchant: String? = "Merchant",
        category: String = "其他",
        details: PendingExpenseDetails = PendingExpenseDetails(),
    ): Expense = Expense(
        id = id,
        publicId = "pub-$id",
        amountCents = amountCents,
        originalCurrency = details.originalCurrencyCode,
        originalCurrencyCode = details.originalCurrencyCode,
        originalAmountMinor = if (details.useAmountAsOriginalMinor) amountCents else details.originalAmountMinor,
        merchant = merchant,
        category = category,
        note = null,
        source = "manual",
        imagePath = details.imagePath,
        thumbnailPath = null,
        imageHash = null,
        rawText = null,
        confidence = null,
        duplicateStatus = details.duplicateStatus,
        duplicateOfId = null,
        duplicateReason = null,
        tags = null,
        valueScore = null,
        regretScore = null,
        status = details.status,
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
    val enrichmentTasks: FakePendingEnrichmentTaskReader = FakePendingEnrichmentTaskReader(),
) : PendingReviewActions {
    // Mutable so tests can simulate backend role demotion mid-flow (V11):
    // the existing canModifyLedger = false ctor arg still works for
    // "viewer from the start" scenarios.
    var canModifyLedgerFlag: Boolean = canModifyLedger

    var pending: List<Expense> = pending

    // A3: 本地缓存种子源，与 [pending]（网络源）分开，便于测「缓存先铺、网络后替」。
    var cachedPending: List<Expense> = emptyList()
    var cachedConfirmed: List<Expense> = emptyList()
    var getCachedPendingResponder: (suspend () -> Result<List<Expense>>)? = null

    var updateResponder: (suspend (Long, ExpenseDraft) -> Result<Expense>)? = null
    var saveAndConfirmResponder: (suspend (LogicalSessionBinding, Expense, ExpenseDraft) -> Result<Expense>)? = null
    var saveResponder: (suspend (LogicalSessionBinding, Expense, ExpenseDraft) -> Result<Expense>)? = null
    var undoRejectResponder: (suspend (LogicalSessionBinding, Expense) -> Result<Unit>)? = null
    val commands = MutableStateFlow<List<PendingExpenseCommand>>(emptyList())
    private var nextCommandId = 1L
    val admissions = mutableListOf<Pair<LogicalSessionBinding, ExpenseCommandAcceptance>>()
    var saveAndConfirmCalls = 0
        private set
    var confirmBatchCalls = 0
        private set
    var fetchPendingResponder: (suspend () -> Result<List<Expense>>)? = null
    var thumbnailResponder: (suspend (Long) -> Result<ProtectedImage>)? = null
    // W1: drives [uploadScreenshot] so the share-multi-image path can be unit
    // tested. Default (unset) keeps the historical "upload not exercised"
    // failure so existing tests are unaffected. Receives the file name per call.

    var updateCalls: Int = 0
        private set
    var confirmCalls: Int = 0
        private set
    var rejectCalls: Int = 0
        private set
    var markNotDuplicateCalls: Int = 0
        private set
    var fetchPendingCalls: Int = 0
        private set
    val confirmedIds = mutableListOf<Long>()

    override fun canModifyLedger(): Boolean = canModifyLedgerFlag

    override fun observeActiveLedgerId(): Flow<String?> = activeLedgerFlow

    override fun currentActiveLedgerId(): String? = activeLedgerIdProvider()

    override fun observeConfirmed(): Flow<List<Expense>> = flowOf(cachedConfirmed)

    val uploadIntents = FakeUploadIntentActions(
        LedgerAccessContext(uploadTestBinding().copy(ledgerId = activeLedgerIdProvider() ?: (activeLedgerFlow as? StateFlow<String?>)?.value ?: "test-ledger"), canModifyLedger),
        activeLedgerFlow,
    )

    var commandAccessSource: UploadIntentActions = uploadIntents

    override suspend fun fetchPending(): Result<List<Expense>> {
        fetchPendingCalls += 1
        fetchPendingResponder?.let { return it() }
        return Result.success(pending)
    }

    var getCachedPendingCalls: Int = 0
        private set

    override suspend fun getCachedPending(): Result<List<Expense>> {
        getCachedPendingCalls += 1
        getCachedPendingResponder?.let { return it() }
        return Result.success(cachedPending)
    }

    // refresh() 现在走 syncPending；在 fake 里委托给 fetchPending，让既有
    // fetchPendingResponder / fetchPendingCalls 驱动的 refresh 测试无改动通过
    // （无真实 Room，sync 与 fetch 在 fake 里等价）。
    override suspend fun syncPending(): Result<List<Expense>> = fetchPending()

    override suspend fun fetchThumbnail(id: Long): Result<ProtectedImage> =
        thumbnailResponder?.invoke(id)
            ?: Result.failure(IllegalStateException("no thumbnail in tests"))

    override fun observeExpenseCommands(): Flow<ExpenseCommandObservation> = combine(
        commandAccessSource.observeUploadIntents(), commands,
    ) { uploads, rows ->
        val binding = uploads.access?.binding
        ExpenseCommandObservation(uploads.access, rows.filter {
            it.row.ownerKey == binding?.ownerKey && it.row.ledgerId == binding?.ledgerId &&
                it.row.serverUrl == binding?.serverUrl
        })
    }

    private fun admit(
        binding: LogicalSessionBinding, expense: Expense, types: List<PendingMutationType>,
    ): ExpenseCommandAcceptance {
        val rows = types.map { observedExpenseCommand(nextCommandId++, expense, it, PendingMutationStatus.Pending, binding) }
        commands.value += rows
        return ExpenseCommandAcceptance(expense, rows.map { it.row.id }).also { admissions += binding to it }
    }

    fun publishCommand(
        expenseId: Long, type: PendingMutationType, status: PendingMutationStatus,
        acceptedExpense: Expense? = null, error: String? = null,
    ) {
        val original = commands.value.last { it.row.targetId == "expense:$expenseId" && it.row.type == type }
        commands.value = commands.value.map {
            if (it.row.id == original.row.id) it.copy(row = it.row.copy(status = status, lastError = error),
                acceptedExpense = acceptedExpense) else it
        }
    }

    fun dropCommands(expenseId: Long, type: PendingMutationType? = null) {
        commands.value = commands.value.filterNot {
            it.row.targetId == "expense:$expenseId" && (type == null || it.row.type == type)
        }
    }

    override suspend fun saveExpenseAllowingOffline(
        expectedBinding: LogicalSessionBinding, id: Long, draft: ExpenseDraft, baseline: Expense,
    ): Result<ExpenseCommandAcceptance> {
        updateCalls += 1
        val projection = saveResponder?.invoke(expectedBinding, baseline, draft)
            ?: updateResponder?.invoke(id, draft) ?: error("save responder not set")
        return projection.map { admit(expectedBinding, it, listOf(PendingMutationType.PatchExpense)) }
    }

    override suspend fun saveAndConfirmExpense(
        expectedBinding: LogicalSessionBinding, expense: Expense, draft: ExpenseDraft,
    ): Result<ExpenseCommandAcceptance> {
        saveAndConfirmCalls += 1
        return requireNotNull(saveAndConfirmResponder)(expectedBinding, expense, draft).map {
            admit(expectedBinding, it, listOf(PendingMutationType.PatchExpense, PendingMutationType.ConfirmExpense))
        }
    }

    override suspend fun confirmExpenses(
        expectedBinding: LogicalSessionBinding, expenses: List<Expense>,
    ): Result<List<ExpenseCommandAcceptance>> {
        confirmBatchCalls += 1
        confirmedIds += expenses.map { it.id }
        return Result.success(expenses.map { admit(expectedBinding, it, listOf(PendingMutationType.ConfirmExpense)) })
    }

    override suspend fun confirmExpenseAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance> {
        confirmCalls += 1
        confirmedIds += expense.id
        return Result.success(admit(expectedBinding, expense, listOf(PendingMutationType.ConfirmExpense)))
    }

    override suspend fun rejectExpenseAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance> {
        rejectCalls += 1
        return Result.success(admit(expectedBinding, expense, listOf(PendingMutationType.RejectExpense)))
    }

    override suspend fun undoRejectExpense(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance> {
        val admitted = undoRejectResponder?.invoke(expectedBinding, expense) ?: Result.success(Unit)
        return admitted.map { admit(expectedBinding, expense, listOf(PendingMutationType.UndoExpense)) }
    }

    override suspend fun markNotDuplicateAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance> {
        markNotDuplicateCalls += 1
        return Result.success(admit(expectedBinding, expense, listOf(PendingMutationType.MarkNotDuplicate)))
    }

    override suspend fun categories(): Result<List<String>> = Result.success(categoryOptions)


}

internal class FakePendingEnrichmentTaskReader : PendingEnrichmentTaskReader {
    var responder: (suspend (String) -> Result<PendingEnrichmentTask>)? = null
    var calls: Int = 0
        private set
    val fetchedTaskIds = mutableListOf<String>()
    val fetchedBindings = mutableListOf<LogicalSessionBinding>()

    override suspend fun fetchPendingEnrichmentTask(
        publicId: String,
        expectedBinding: LogicalSessionBinding,
    ): Result<PendingEnrichmentTask> {
        calls += 1
        fetchedTaskIds += publicId
        fetchedBindings += expectedBinding
        responder?.let { return it(publicId) }
        return Result.success(
            PendingEnrichmentTask(
                status = "completed",
                outcome = PendingEnrichmentOutcome.NoResult,
            ),
        )
    }
}

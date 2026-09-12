package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.dto.ExpenseRecognizeTextRequestDto
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.mergeExpenseCategories
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map
import java.util.UUID

internal class ExpensePendingRepository(private val core: ExpenseRepositoryCore) : PendingReviewActions {
    private val pendingSyncCoordinator = PendingSyncCoordinator()
    private val outbox get() = core.offlineMutations.outbox

    override fun canModifyLedger(): Boolean = core.canModifyLedger()
    override fun observeActiveLedgerId(): Flow<String?> = core.observeActiveLedgerId()
    override fun currentActiveLedgerId(): String? = core.currentActiveLedgerId()
    override suspend fun fetchPending(): Result<List<Expense>> = syncPending()
    override suspend fun getCachedPending(): Result<List<Expense>> = core.errorHandler.safeCall { core.getCachedPending() }
    override fun observeConfirmed(): Flow<List<Expense>> = core.observeConfirmed()
    override suspend fun syncPending(): Result<List<Expense>> = core.errorHandler.safeCall {
        val ledgerId = core.ledgerRequestGuard.bind().ledgerId
        pendingSyncCoordinator.sync(ledgerId) {
            core.syncPendingFromService(core.ledgerRequestGuard.bind(expectedLedgerId = ledgerId))
        }
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    override fun observeExpenseCommands(): Flow<ExpenseCommandObservation> = core.apiProvider.observeActiveLedgerAccess()
        .flatMapLatest { access ->
            if (access == null) flowOf(ExpenseCommandObservation(null, emptyList()))
            else outbox.observeActiveByTypes(PENDING_EXPENSE_COMMAND_TYPES, includeCompleted = true).map { rows ->
                val current = access.takeIf { core.ledgerRequestGuard.captureLogicalBinding() == it.binding }
                ExpenseCommandObservation(current, if (current == null) emptyList() else rows.filter {
                    it.ownerKey == current.binding.ownerKey && it.ledgerId == current.binding.ledgerId
                }.map { row -> PendingExpenseCommand(row, expenseAcceptanceReceiptSnapshot(row)?.toDomain()) })
            }.distinctUntilChanged()
        }.distinctUntilChanged()

    override suspend fun saveExpenseAllowingOffline(
        expectedBinding: LogicalSessionBinding, id: Long, draft: ExpenseDraft, baseline: Expense,
    ): Result<ExpenseCommandAcceptance> = core.errorHandler.safeCall {
        require(id == baseline.id) { "账单已变化，请重新打开。" }
        ExpenseCommandAcceptance(projectOptimisticExpense(baseline, draft),
            admit(expectedBinding, listOf(patchIntent(baseline, draft))))
    }

    override suspend fun saveAndConfirmExpense(
        expectedBinding: LogicalSessionBinding, expense: Expense, draft: ExpenseDraft,
    ): Result<ExpenseCommandAcceptance> = core.errorHandler.safeCall {
        ExpenseCommandAcceptance(projectOptimisticExpense(expense, draft), admit(expectedBinding,
            listOf(patchIntent(expense, draft), stateIntent(PendingMutationType.ConfirmExpense, expense))))
    }

    override suspend fun confirmExpenses(
        expectedBinding: LogicalSessionBinding, expenses: List<Expense>,
    ): Result<List<ExpenseCommandAcceptance>> = core.errorHandler.safeCall {
        require(expenses.isNotEmpty() && expenses.map(::expenseOutboxTargetId).distinct().size == expenses.size) {
            "请重新选择待确认账单。"
        }
        val ids = admit(expectedBinding, expenses.map { stateIntent(PendingMutationType.ConfirmExpense, it) })
        expenses.zip(ids) { expense, id -> ExpenseCommandAcceptance(expense, listOf(id)) }
    }

    override suspend fun confirmExpenseAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance> = acceptState(expectedBinding, expense, PendingMutationType.ConfirmExpense)

    override suspend fun rejectExpenseAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance> = acceptState(expectedBinding, expense, PendingMutationType.RejectExpense)

    override suspend fun markNotDuplicateAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance> = acceptState(expectedBinding, expense, PendingMutationType.MarkNotDuplicate)

    override suspend fun undoRejectExpense(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance> = core.errorHandler.safeCall {
        require(expense.status == "rejected" && expense.id > 0L && expense.rejectedAt != null) {
            "无法读取原拒绝结果，请先核对账单。"
        }
        ExpenseCommandAcceptance(expense, admit(expectedBinding, listOf(stateIntent(PendingMutationType.UndoExpense, expense))))
    }

    suspend fun retryOcrAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense,
    ): Result<ExpenseCommandAcceptance> = acceptState(expectedBinding, expense, PendingMutationType.RetryOcr)

    suspend fun recognizeTextAllowingOffline(
        expectedBinding: LogicalSessionBinding, expense: Expense, rawText: String,
    ): Result<ExpenseCommandAcceptance> = core.errorHandler.safeCall {
        require(rawText.isNotBlank()) { "请先粘贴待识别文字。" }
        requireBaseline(expense)
        val intent = PendingMutationIntent(PendingMutationType.RecognizeText, expenseOutboxTargetId(expense),
            core.offlineMutations.recognizeTextAdapter.toJson(ExpenseRecognizeTextRequestDto(0L, rawText)),
            expense.rowVersion, UUID.randomUUID().toString())
        ExpenseCommandAcceptance(expense, admit(expectedBinding, listOf(intent)))
    }

    private suspend fun acceptState(
        binding: LogicalSessionBinding, expense: Expense, type: PendingMutationType,
    ): Result<ExpenseCommandAcceptance> = core.errorHandler.safeCall {
        ExpenseCommandAcceptance(expense, admit(binding, listOf(stateIntent(type, expense))))
    }

    private suspend fun admit(binding: LogicalSessionBinding, intents: List<PendingMutationIntent>): List<Long> =
        outbox.enqueueExpenseBatch(core.ledgerRequestGuard.bindExact(binding), intents) { rows ->
            if (!core.canModifyLedger()) throw RepositoryException("当前角色为只读，无法修改账本。")
            requireExpenseRefreshComplete(rows)
        }

    private fun requireBaseline(expense: Expense) {
        require(expense.hasExpenseMutationBaseline()) { "缺少账单版本，请重新打开后操作。" }
    }

    private fun patchIntent(expense: Expense, draft: ExpenseDraft): PendingMutationIntent {
        requireBaseline(expense)
        return PendingMutationIntent(PendingMutationType.PatchExpense, expenseOutboxTargetId(expense),
            core.offlineMutations.patchExpenseAdapter.toJson(draft.toRequest(baseline = expense).copy(expectedRowVersion = null)),
            expense.rowVersion, UUID.randomUUID().toString())
    }

    private fun stateIntent(type: PendingMutationType, expense: Expense): PendingMutationIntent {
        requireBaseline(expense)
        return PendingMutationIntent(type, expenseOutboxTargetId(expense),
            core.offlineMutations.expenseStateTokenAdapter.toJson(ExpenseStateTokenRequest(0L)),
            expense.rowVersion, UUID.randomUUID().toString())
    }

    private fun projectOptimisticExpense(baseline: Expense, draft: ExpenseDraft): Expense {
        // Only fields the draft can change get overwritten; the rest
        // (timestamps, server-side derived state) stay at baseline.
        // A queued manual FX intent is the exception: the old converted amount
        // and ready snapshot are no longer true after the rate changes. Keep
        // the user's original-side edits visible, but wait for the server to
        // calculate and return the new home-side snapshot.
        val projected = baseline.copy(
            amountCents = draft.amountCents ?: baseline.amountCents,
            originalCurrencyCode = draft.originalCurrencyCode ?: baseline.originalCurrencyCode,
            originalAmountMinor = draft.originalAmountMinor ?: baseline.originalAmountMinor,
            merchant = draft.merchant ?: baseline.merchant,
            category = draft.category ?: baseline.category,
            note = draft.note ?: baseline.note,
            expenseTime = draft.expenseTime ?: baseline.expenseTime,
            tags = draft.tags ?: baseline.tags,
            valueScore = draft.valueScore ?: baseline.valueScore,
            regretScore = draft.regretScore ?: baseline.regretScore,
        )
        if (draft.manualExchangeRate == null) return projected
        return projected.copy(
            amountCents = null,
            homeAmountCents = null,
            fxRate = null,
            fxRateDate = null,
            fxSource = null,
            exchangeRateToCny = null,
            exchangeRateDate = null,
            exchangeRateSource = null,
            fxStatus = FxContract.StatusPending,
        )
    }

    override suspend fun fetchThumbnail(id: Long): Result<ProtectedImage> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        bound.call { core.readProtectedImage(it.expenseThumbnail(id)) }
    }
    override suspend fun categories(): Result<List<String>> = core.errorHandler.safeCall {
        core.ledgerRequestGuard.guardedCall { api -> mergeExpenseCategories(api.categories().items) }
    }
}

package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseRevisionPage
import java.util.UUID
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map

internal class ExpenseCorrectionRepository(
    private val core: ExpenseRepositoryCore,
    private val outbox: OutboxRepository,
    private val adapter: JsonAdapter<ExpenseCorrectionPayload>,
    private val legacyAdapter: JsonAdapter<ExpenseCorrectionRequestDto>,
) {
    suspend fun publishDelivered(row: OutboxRow, expense: ExpenseDto) {
        val bound = core.ledgerRequestGuard.bind(expectedLedgerId = row.ledgerId)
        bound.serviceFor(row.bindingOrNull() ?: throw RepositoryException("原提交身份不可核对。"))
        core.syncConfirmedFromService(bound, requiredCorrection = expense)
    }

    suspend fun fetchRevisions(id: Long, page: Int, pageSize: Int, snapshotRevision: Long? = null): Result<ExpenseRevisionPage> =
        core.errorHandler.safeCall {
            core.ledgerRequestGuard.bind().call { it.expenseRevisions(id, page, pageSize, snapshotRevision) }.toDomain()
        }

    @OptIn(ExperimentalCoroutinesApi::class)
    fun observe(): Flow<ExpenseCorrectionObservation> = core.apiProvider.observeActiveLedgerAccess().flatMapLatest { access ->
        if (access == null) flowOf(ExpenseCorrectionObservation(null, emptyList()))
        else outbox.observeActiveByTypes(setOf(PendingMutationType.CorrectExpense), includeCompleted = true).map { rows ->
            if (core.ledgerRequestGuard.captureLogicalBinding() != access.binding) ExpenseCorrectionObservation(null, emptyList())
            else ExpenseCorrectionObservation(access, rows.map { row ->
                val intent = adapter.readSupportedCorrection(row)
                PendingExpenseCorrection(row, intent, if (intent == null) {
                    adapter.readDisplayCorrection(row) ?: legacyAdapter.readCorrectionJson(row.payloadJson)
                } else null)
            })
        }
    }

    suspend fun submit(expectedBinding: LogicalSessionBinding, expense: Expense, correction: ExpenseCorrectionDraft): Result<Long> =
        core.errorHandler.safeCall {
            if (!core.canModifyLedger()) throw RepositoryException("当前角色为只读，无法更正账本。")
            if (expense.status != "confirmed" || expense.pendingSync || expense.id <= 0 || expense.rowVersion <= 0) {
                throw RepositoryException("请先读取当前已确认账单，再核对更正。")
            }
            val bound = core.ledgerRequestGuard.bindExact(expectedBinding)
            val target = "expense:${expense.id}"
            if (outbox.activeForTarget(bound, target).isNotEmpty() || observe().first().corrections.any {
                    it.row.targetId == target && (!it.hasSupportedIntent || it.refreshRequired)
                }) throw RepositoryException("这笔账单有待处理的提交，请先查看原提交。")
            val payload = ExpenseCorrectionPayload(1, expense.id, expense.merchant,
                expense.originalCurrencyCodeRaw ?: expense.originalCurrencyCode.storageKey, expense.originalAmountMinor, expense.homeCurrencyCode ?: expense.homeCurrency.storageKey,
                expectedBinding.ownerKey, expectedBinding.ledgerId, expectedBinding.sessionGeneration, expectedBinding.bindingRevision,
                correction.toRequest(expense.rowVersion))
            outbox.enqueue(boundRequest = bound, intent = PendingMutationIntent(
                type = PendingMutationType.CorrectExpense, targetId = target, payloadJson = adapter.toJson(payload),
                expectedRowVersion = expense.rowVersion, idempotencyKey = UUID.randomUUID().toString()))
        }

    suspend fun recover(expectedBinding: LogicalSessionBinding, rowId: Long, drop: Boolean): Result<Unit> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bindExact(expectedBinding)
        val current = observe().first()
        if (current.access?.binding != expectedBinding) throw RepositoryException("账本连接已变化，请重新打开账单。")
        val pending = current.corrections.singleOrNull { it.row.id == rowId } ?: throw RepositoryException("原提交状态已变化，请重新查看。")
        bound.requireStillActive()
        val changed = when {
            drop && pending.canDiscard -> {
                if (pending.hasSupportedIntent && pending.row.lastError != "correction_target_unavailable") {
                    core.fetchAuthoritativeExpense(bound, requireNotNull(pending.expenseId))
                }
                outbox.discardCorrection(bound, pending.row)
            }
            !drop && current.access?.canModify == true && pending.canRetry -> outbox.resolveFailed(rowId, FailedResolution.Retry())
            else -> throw RepositoryException("请核对当前事实后明确重新提交；原提交不能直接重试或覆盖。")
        }
        if (!changed) throw RepositoryException("原提交状态已变化，请重新查看。")
    }
}

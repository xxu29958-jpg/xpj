package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.data.remote.dto.ExpenseCorrectionResponseDto
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseCorrectionOutcome
import com.ticketbox.domain.model.ExpenseRevisionPage
import kotlinx.coroutines.CancellationException
import java.io.IOException
import java.util.UUID

private data class QueuedExpenseCorrection(
    val bound: BoundLedgerRequest,
    val outbox: OutboxRepository,
    val adapter: JsonAdapter<ExpenseCorrectionRequestDto>,
    val expense: Expense,
    val request: ExpenseCorrectionRequestDto,
    val idempotencyKey: String,
)

internal class ExpenseCorrectionRepository(
    private val core: ExpenseRepositoryCore,
) {
    suspend fun fetchRevisions(
        id: Long,
        page: Int,
        pageSize: Int,
    ): Result<ExpenseRevisionPage> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        bound.call { it.expenseRevisions(id, page, pageSize) }.toDomain()
    }

    suspend fun correctAllowingOffline(
        expense: Expense,
        correction: ExpenseCorrectionDraft,
    ): Result<ExpenseCorrectionOutcome> = core.errorHandler.safeCall {
        if (!core.canModifyLedger()) {
            throw RepositoryException("当前角色为只读，无法更正账本。")
        }
        if (expense.status != "confirmed" || expense.pendingSync || expense.id <= 0L) {
            throw RepositoryException("这笔账单还不能更正。")
        }
        val bound = core.ledgerRequestGuard.bind()
        val request = correction.toRequest(expense.rowVersion)
        val idempotencyKey = UUID.randomUUID().toString()
        val outbox = core.outbox
        val adapter = core.correctionAdapter
        if (outbox == null || adapter == null || expense.rowVersion == 0L) {
            val response = bound.call {
                it.correctExpense(expense.id.toString(), request, idempotencyKey)
            }
            return@safeCall syncedOutcome(response, bound)
        }

        if (core.hasUnresolvedQueuedMutationsFor(bound, expenseOutboxTargetId(expense))) {
            enqueue(QueuedExpenseCorrection(bound, outbox, adapter, expense, request, idempotencyKey))
            return@safeCall ExpenseCorrectionOutcome.Queued(expense.projectCorrection(correction))
        }
        val response = try {
            bound.call {
                it.correctExpense(expense.id.toString(), request, idempotencyKey)
            }
        } catch (networkError: IOException) {
            enqueue(QueuedExpenseCorrection(bound, outbox, adapter, expense, request, idempotencyKey))
            return@safeCall ExpenseCorrectionOutcome.Queued(expense.projectCorrection(correction))
        }
        syncedOutcome(response, bound)
    }

    private suspend fun enqueue(command: QueuedExpenseCorrection) {
        command.outbox.enqueue(
            boundRequest = command.bound,
            intent = PendingMutationIntent(
                type = PendingMutationType.CorrectExpense,
                targetId = expenseOutboxTargetId(command.expense),
                payloadJson = command.adapter.toJson(command.request.copy(expectedRowVersion = 0L)),
                expectedRowVersion = command.expense.rowVersion,
                idempotencyKey = command.idempotencyKey,
            ),
        )
    }

    private suspend fun syncedOutcome(
        response: ExpenseCorrectionResponseDto,
        bound: BoundLedgerRequest,
    ): ExpenseCorrectionOutcome.Synced {
        val refreshPending = try {
            core.cacheIfConfirmed(response.expense, bound)
            false
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (bindingError: RepositoryException) {
            throw bindingError
        } catch (_: Exception) {
            true
        }
        return ExpenseCorrectionOutcome.Synced(
            expense = response.expense.toDomain(),
            revision = response.revision.toDomain(),
            refreshPending = refreshPending,
        )
    }
}

package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseItemDraft
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ExpenseSplitDraft
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.NotificationDraft
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.RecurringCandidate
import java.io.IOException

internal class ExpenseDetailRepository(
    private val core: ExpenseRepositoryCore,
) {
    suspend fun fetchExpense(id: Long): Result<Expense> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        core.cacheIfConfirmed(bound.call { it.expense(id) }, bound.ledgerId).toDomain()
    }

    suspend fun fetchExpenseItems(id: Long): Result<ExpenseItems> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        bound.call { it.expenseItems(id) }.toDomain()
    }

    suspend fun replaceExpenseItems(
        id: Long,
        items: List<ExpenseItemDraft>,
        expectedUpdatedAt: String,
    ): Result<ExpenseItems> = core.errorHandler.safeCall {
        if (!core.canModifyLedger()) {
            throw RepositoryException("当前角色为只读，无法修改账本。")
        }
        val bound = core.ledgerRequestGuard.bind()
        val updated = bound.call {
            it.replaceExpenseItems(
                id,
                ExpenseItemReplaceRequestDto(
                    expectedUpdatedAt = expectedUpdatedAt,
                    items = items.map { item -> item.toRequest() },
                ),
            )
        }
        updated.toDomain()
    }

    suspend fun acknowledgeExpenseItemsMismatch(
        id: Long,
        expectedUpdatedAt: String,
    ): Result<ExpenseItems> = core.errorHandler.safeCall {
        if (!core.canModifyLedger()) {
            throw RepositoryException("当前角色为只读，无法修改账本。")
        }
        val bound = core.ledgerRequestGuard.bind()
        // ADR-0038 PR-2e: send the token so server's atomic UPDATE WHERE
        // items_sum_status='mismatch_known', updated_at=expected rejects
        // stale "原小票如此" clicks against a peer-edited row.
        bound.call {
            it.acknowledgeExpenseItemsMismatch(
                id,
                com.ticketbox.data.remote.dto.ExpenseStateTokenRequest(
                    expectedUpdatedAt = expectedUpdatedAt,
                ),
            )
        }.toDomain()
    }

    suspend fun fetchExpenseSplits(id: Long): Result<ExpenseSplits> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        bound.call { it.expenseSplits(id) }.toDomain()
    }

    suspend fun replaceExpenseSplits(
        id: Long,
        splits: List<ExpenseSplitDraft>,
        expectedUpdatedAt: String,
    ): Result<ExpenseSplits> = core.errorHandler.safeCall {
        if (!core.canModifyLedger()) {
            throw RepositoryException("当前角色为只读，无法修改账本。")
        }
        val bound = core.ledgerRequestGuard.bind()
        val updated = bound.call {
            it.replaceExpenseSplits(
                id,
                ExpenseSplitReplaceRequestDto(
                    expectedUpdatedAt = expectedUpdatedAt,
                    splits = splits.map { split -> split.toRequest() },
                ),
            )
        }
        updated.toDomain()
    }

    suspend fun createNotificationDraft(
        draft: NotificationDraft,
        expectedLedgerId: String? = null,
    ): Result<Expense> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind(expectedLedgerId = expectedLedgerId)
        val created = bound.call { it.createNotificationDraft(draft.toRequest()) }
        created.toDomain()
    }

    suspend fun retryOcr(id: Long, expectedUpdatedAt: String): Result<Expense> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        val retried = bound.call { it.retryOcr(id, ExpenseStateTokenRequest(expectedUpdatedAt)) }
        retried.toDomain()
    }

    /**
     * ADR-0038 PR-2g.8: offline-aware OCR retry. Token-only POST like
     * confirm/reject (shares [ExpenseRepositoryCore.enqueueStateTransition]).
     * The Queued projection is the expense UNCHANGED — OCR re-runs
     * server-side so there's nothing to project optimistically; the UI
     * just shows the "联网后重试识别" hint and the worker replays the
     * retry once connectivity returns.
     */
    suspend fun retryOcrAllowingOffline(expense: Expense): Result<ExpenseStateOutcome> =
        core.errorHandler.safeCall {
            val bound = core.ledgerRequestGuard.bind()
            try {
                val retried = bound.call {
                    it.retryOcr(expense.id, ExpenseStateTokenRequest(expense.updatedAt))
                }
                ExpenseStateOutcome.Synced(retried.toDomain()) as ExpenseStateOutcome
            } catch (networkError: IOException) {
                core.enqueueStateTransition(
                    bound = bound,
                    type = PendingMutationType.RetryOcr,
                    expense = expense,
                    networkError = networkError,
                )
                ExpenseStateOutcome.Queued(expense) as ExpenseStateOutcome
            }
        }

    suspend fun fetchDuplicates(): Result<List<Expense>> = core.errorHandler.safeCall {
        core.ledgerRequestGuard.guardedCall { api ->
            api.duplicates().map { it.toDomain() }
        }
    }

    suspend fun fetchImage(id: Long): Result<ProtectedImage> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        bound.call { core.readProtectedImage(it.expenseImage(id)) }
    }

    suspend fun recurringCandidates(): Result<List<RecurringCandidate>> = core.errorHandler.safeCall {
        core.ledgerRequestGuard.guardedCall { api ->
            api.recurringCandidates(timezone = core.currentTimezoneId()).items.map { it.toDomain() }
        }
    }
}

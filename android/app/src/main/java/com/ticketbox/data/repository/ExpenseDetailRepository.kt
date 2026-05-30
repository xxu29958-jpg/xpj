package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseItemDraft
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ItemsSumStatus
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

    /**
     * ADR-0038 PR-2g.9: offline-aware "原小票如此" acknowledge. Token-only
     * POST like confirm/reject, but the response is [ExpenseItems] (not
     * an Expense) and the server bumps the parent's ``updated_at``
     * WITHOUT returning it — so the online success path follows up with
     * a [fetchExpense] (the ViewModel does that, only on Synced).
     *
     *  - direct 2xx → [ItemsAckOutcome.Synced] with the server items.
     *  - IOException → [ItemsAckOutcome.Queued] with [currentItems]
     *    projected to ``mismatch_acknowledged`` (the badge clears
     *    immediately); the row enqueues and replays on connectivity-up.
     *  - HttpException → ``Result.failure``.
     *
     * Takes [currentItems] (what the user is looking at) so the Queued
     * branch can build the optimistic projection — the same baseline
     * reason the other offline methods take the pre-mutation snapshot.
     */
    suspend fun acknowledgeItemsMismatchAllowingOffline(
        expense: Expense,
        currentItems: ExpenseItems,
    ): Result<ItemsAckOutcome> = core.errorHandler.safeCall {
        if (!core.canModifyLedger()) {
            throw RepositoryException("当前角色为只读，无法修改账本。")
        }
        val bound = core.ledgerRequestGuard.bind()
        try {
            val items = bound.call {
                it.acknowledgeExpenseItemsMismatch(
                    expense.id,
                    ExpenseStateTokenRequest(expectedUpdatedAt = expense.updatedAt),
                )
            }.toDomain()
            ItemsAckOutcome.Synced(items) as ItemsAckOutcome
        } catch (networkError: IOException) {
            core.enqueueStateTransition(
                bound = bound,
                type = PendingMutationType.AcknowledgeItemsMismatch,
                expense = expense,
                networkError = networkError,
            )
            ItemsAckOutcome.Queued(
                currentItems.copy(itemsSumStatus = ItemsSumStatus.MISMATCH_ACKNOWLEDGED),
            ) as ItemsAckOutcome
        }
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

/**
 * ADR-0038 PR-2g.9 sealed result for
 * [ExpenseDetailRepository.acknowledgeItemsMismatchAllowingOffline].
 * Carries [ExpenseItems] (not Expense) — parallel-defined alongside
 * [ExpenseStateOutcome] rather than reused, same convention as the
 * other outcome types. On [Synced] the ViewModel additionally
 * re-fetches the parent expense for its bumped token; on [Queued] it
 * keeps the current (pre-ack) token and shows the optimistic items.
 */
sealed interface ItemsAckOutcome {
    val items: ExpenseItems

    /** Server confirmed the acknowledge; [items] is the server snapshot. */
    data class Synced(override val items: ExpenseItems) : ItemsAckOutcome

    /**
     * Network failed; the acknowledge is queued and [items] is the
     * optimistic projection (``itemsSumStatus = mismatch_acknowledged``).
     */
    data class Queued(override val items: ExpenseItems) : ItemsAckOutcome
}

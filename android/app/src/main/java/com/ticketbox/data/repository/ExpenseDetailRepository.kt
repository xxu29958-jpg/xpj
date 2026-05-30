package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseItem
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

    /**
     * PR-D: offline-aware items replace. Body-carrying PUT (mirror of the
     * [ExpensePendingRepository] PATCH offline path).
     *  - direct 2xx → [ReplaceItemsOutcome.Synced] with the server items.
     *  - IOException → [ReplaceItemsOutcome.Queued] with an optimistic
     *    projection of the user's edited items (recomputed total + mismatch);
     *    the row enqueues and replays on connectivity-up.
     *  - HttpException → ``Result.failure``.
     *
     * The optimistic projection is display-only — the server recomputes
     * ``items_sum_status`` authoritatively when the queued PUT replays.
     */
    suspend fun replaceExpenseItemsAllowingOffline(
        expense: Expense,
        items: List<ExpenseItemDraft>,
        currentItems: ExpenseItems,
    ): Result<ReplaceItemsOutcome> = core.errorHandler.safeCall {
        if (!core.canModifyLedger()) {
            throw RepositoryException("当前角色为只读，无法修改账本。")
        }
        val bound = core.ledgerRequestGuard.bind()
        val request = ExpenseItemReplaceRequestDto(
            expectedUpdatedAt = expense.updatedAt,
            items = items.map { it.toRequest() },
        )
        try {
            val saved = bound.call { it.replaceExpenseItems(expense.id, request) }.toDomain()
            ReplaceItemsOutcome.Synced(saved) as ReplaceItemsOutcome
        } catch (networkError: IOException) {
            val outbox = core.outbox
            val adapter = core.replaceItemsAdapter
            val token = expense.updatedAt
            if (outbox == null || adapter == null || token.isEmpty()) {
                // Outbox wiring missing OR baseline lacked a token — fall back
                // to the failure path so we don't pretend we saved.
                throw networkError
            }
            // Session race guard: an IOException jumps past bound.call's
            // post-check, so re-assert the session before queuing (a row
            // queued under ledger A must not land in ledger B after a switch).
            bound.requireStillActive()
            // Strip the token from the payload — the row's expectedUpdatedAt is
            // the single source of truth; the dispatcher overwrites it on replay.
            outbox.enqueue(
                type = PendingMutationType.ReplaceItems,
                targetId = "expense:${expense.id}",
                payloadJson = adapter.toJson(request.copy(expectedUpdatedAt = "")),
                expectedUpdatedAt = token,
            )
            ReplaceItemsOutcome.Queued(projectOptimisticItems(currentItems, items)) as ReplaceItemsOutcome
        }
    }

    /**
     * Build the optimistic [ExpenseItems] the server WOULD return once the
     * queued PUT replays: the user's edited rows + a recomputed total and
     * mismatch against the (unchanged) parent amount. Item timestamps are left
     * blank — they aren't surfaced in the editor and the server overwrites the
     * whole snapshot on replay.
     */
    private fun projectOptimisticItems(
        currentItems: ExpenseItems,
        drafts: List<ExpenseItemDraft>,
    ): ExpenseItems {
        val projected = drafts.mapIndexed { index, draft ->
            ExpenseItem(
                publicId = "local-pending-$index",
                position = index,
                kind = draft.kind,
                name = draft.name,
                quantityText = draft.quantityText,
                unitPriceCents = draft.unitPriceCents,
                amountCents = draft.amountCents,
                category = draft.category.orEmpty(),
                rawText = draft.rawText,
                confidence = draft.confidence,
                isOcrDraft = false,
                createdAt = "",
                updatedAt = "",
            )
        }
        val total = drafts.sumOf { it.amountCents ?: 0L }
        val parent = currentItems.parentAmountCents
        val mismatch = parent?.let { total - it }
        val status = when {
            projected.isEmpty() -> ItemsSumStatus.NO_ITEMS
            mismatch == null || mismatch == 0L -> ItemsSumStatus.MATCHED
            else -> ItemsSumStatus.MISMATCH_KNOWN
        }
        return currentItems.copy(
            itemsTotalAmountCents = total,
            mismatchCents = mismatch,
            itemsSumStatus = status,
            items = projected,
        )
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

/**
 * PR-D sealed result for [ExpenseDetailRepository.replaceExpenseItemsAllowingOffline].
 * Mirrors [ItemsAckOutcome]: on [Synced] the items are the server snapshot; on
 * [Queued] they are the optimistic projection of the user's edit (recomputed
 * total + mismatch), shown immediately while the queued PUT replays.
 */
sealed interface ReplaceItemsOutcome {
    val items: ExpenseItems

    /** Server confirmed the replace; [items] is the server snapshot. */
    data class Synced(override val items: ExpenseItems) : ReplaceItemsOutcome

    /** Network failed; the replace is queued and [items] is the optimistic projection. */
    data class Queued(override val items: ExpenseItems) : ReplaceItemsOutcome
}

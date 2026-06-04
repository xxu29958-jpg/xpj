package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseRecognizeTextRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.ExpenseItem
import com.ticketbox.domain.model.ExpenseItemDraft
import com.ticketbox.domain.model.ExpenseItems
import com.ticketbox.domain.model.ItemsSumStatus
import com.ticketbox.domain.model.ExpenseSplit
import com.ticketbox.domain.model.ExpenseSplitDraft
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.NotificationDraft
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.RecurringCandidate
import java.io.IOException
import java.util.UUID

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
        expectedRowVersion: Long,
    ): Result<ExpenseItems> = core.errorHandler.safeCall {
        if (!core.canModifyLedger()) {
            throw RepositoryException("当前角色为只读，无法修改账本。")
        }
        val bound = core.ledgerRequestGuard.bind()
        val updated = bound.call {
            it.replaceExpenseItems(
                id,
                ExpenseItemReplaceRequestDto(
                    expectedRowVersion = expectedRowVersion,
                    items = items.map { item -> item.toRequest() },
                ),
                // ADR-0042: single-use key — direct-only path, no replay.
                UUID.randomUUID().toString(),
            )
        }
        updated.toDomain()
    }

    suspend fun acknowledgeExpenseItemsMismatch(
        id: Long,
        expectedRowVersion: Long,
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
                    expectedRowVersion = expectedRowVersion,
                ),
                // ADR-0042: single-use key — direct-only path, no replay.
                UUID.randomUUID().toString(),
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
        // ADR-0042: one intent-time key shared by the direct attempt and the
        // outbox replay — a committed-but-unseen acknowledge replays with this
        // SAME key so the server HITs the recorded success instead of false-
        // 409ing on the stale token. The dispatcher replays it from
        // row.idempotencyKey.
        val idempotencyKey = UUID.randomUUID().toString()
        try {
            val items = bound.call {
                it.acknowledgeExpenseItemsMismatch(
                    expense.id,
                    ExpenseStateTokenRequest(expectedRowVersion = expense.rowVersion),
                    idempotencyKey,
                )
            }.toDomain()
            ItemsAckOutcome.Synced(items) as ItemsAckOutcome
        } catch (networkError: IOException) {
            core.enqueueStateTransition(
                bound = bound,
                type = PendingMutationType.AcknowledgeItemsMismatch,
                expense = expense,
                networkError = networkError,
                idempotencyKey = idempotencyKey,
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
            expectedRowVersion = expense.rowVersion,
            items = items.map { it.toRequest() },
        )
        // ADR-0042: one intent-time key shared by the direct attempt and the
        // outbox replay. A committed-but-unseen PUT (it commits server-side but
        // its response is lost) replays with this SAME key so the server HITs
        // the recorded success instead of false-409ing on the now-stale token.
        // The dispatcher replays it from row.idempotencyKey.
        val idempotencyKey = UUID.randomUUID().toString()
        try {
            val saved = bound.call { it.replaceExpenseItems(expense.id, request, idempotencyKey) }.toDomain()
            ReplaceItemsOutcome.Synced(saved) as ReplaceItemsOutcome
        } catch (networkError: IOException) {
            val outbox = core.outbox
            val adapter = core.replaceItemsAdapter
            val token = expense.rowVersion
            if (outbox == null || adapter == null || token == 0L) {
                // Outbox wiring missing OR baseline lacked a token — fall back
                // to the failure path so we don't pretend we saved.
                throw networkError
            }
            // Session race guard: an IOException jumps past bound.call's
            // post-check, so re-assert the session before queuing (a row
            // queued under ledger A must not land in ledger B after a switch).
            bound.requireStillActive()
            // Strip the token from the payload — the row's expectedRowVersion is
            // the single source of truth; the dispatcher overwrites it on replay.
            outbox.enqueue(
                type = PendingMutationType.ReplaceItems,
                targetId = "expense:${expense.id}",
                payloadJson = adapter.toJson(request.copy(expectedRowVersion = 0L)),
                expectedRowVersion = token,
                // Same key as the direct attempt above — the dispatcher replays
                // it from row.idempotencyKey.
                idempotencyKey = idempotencyKey,
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

    /**
     * ADR-0042 Slice E-1: ledger member roster for the splits editor's member
     * checklist. Passthrough to ``GET /api/ledgers/{ledgerId}/members`` scoped
     * to the active ledger; disabled members are kept (the editor greys them
     * read-only so historical attribution isn't dropped).
     */
    suspend fun fetchSplitMembers(): Result<List<FamilyMember>> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        bound.call { it.ledgerMembers(bound.ledgerId) }.members.map { it.toFamilyMember() }
    }

    suspend fun replaceExpenseSplits(
        id: Long,
        splits: List<ExpenseSplitDraft>,
        expectedRowVersion: Long,
    ): Result<ExpenseSplits> = core.errorHandler.safeCall {
        if (!core.canModifyLedger()) {
            throw RepositoryException("当前角色为只读，无法修改账本。")
        }
        val bound = core.ledgerRequestGuard.bind()
        val updated = bound.call {
            it.replaceExpenseSplits(
                id,
                ExpenseSplitReplaceRequestDto(
                    expectedRowVersion = expectedRowVersion,
                    splits = splits.map { split -> split.toRequest() },
                ),
                // ADR-0042: single-use key — direct-only path, no replay.
                UUID.randomUUID().toString(),
            )
        }
        updated.toDomain()
    }

    /**
     * ADR-0042 Slice E-1: offline-aware splits replace. Body-carrying PUT
     * (mirror of [replaceExpenseItemsAllowingOffline]).
     *  - direct 2xx → [ReplaceSplitsOutcome.Synced] with the server splits.
     *  - IOException → [ReplaceSplitsOutcome.Queued] with an optimistic
     *    projection of the user's edited splits (recomputed total + mismatch);
     *    the row enqueues and replays on connectivity-up.
     *  - HttpException → ``Result.failure``.
     *
     * The optimistic projection is display-only — the server recomputes the
     * splits total + mismatch authoritatively when the queued PUT replays.
     */
    suspend fun replaceExpenseSplitsAllowingOffline(
        expense: Expense,
        splits: List<ExpenseSplitDraft>,
        currentSplits: ExpenseSplits,
    ): Result<ReplaceSplitsOutcome> = core.errorHandler.safeCall {
        if (!core.canModifyLedger()) {
            throw RepositoryException("当前角色为只读，无法修改账本。")
        }
        val bound = core.ledgerRequestGuard.bind()
        val request = ExpenseSplitReplaceRequestDto(
            expectedRowVersion = expense.rowVersion,
            splits = splits.map { it.toRequest() },
        )
        // ADR-0042: one intent-time key shared by the direct attempt and the
        // outbox replay. A committed-but-unseen PUT (it commits server-side but
        // its response is lost) replays with this SAME key so the server HITs
        // the recorded success instead of false-409ing on the now-stale token.
        // The dispatcher replays it from row.idempotencyKey.
        val idempotencyKey = UUID.randomUUID().toString()
        try {
            val saved = bound.call { it.replaceExpenseSplits(expense.id, request, idempotencyKey) }.toDomain()
            ReplaceSplitsOutcome.Synced(saved) as ReplaceSplitsOutcome
        } catch (networkError: IOException) {
            val outbox = core.outbox
            val adapter = core.replaceSplitsAdapter
            val token = expense.rowVersion
            if (outbox == null || adapter == null || token == 0L) {
                // Outbox wiring missing OR baseline lacked a token — fall back
                // to the failure path so we don't pretend we saved.
                throw networkError
            }
            // Session race guard: an IOException jumps past bound.call's
            // post-check, so re-assert the session before queuing (a row
            // queued under ledger A must not land in ledger B after a switch).
            bound.requireStillActive()
            // Strip the token from the payload — the row's expectedRowVersion is
            // the single source of truth; the dispatcher overwrites it on replay.
            outbox.enqueue(
                type = PendingMutationType.ReplaceSplits,
                targetId = "expense:${expense.id}",
                payloadJson = adapter.toJson(request.copy(expectedRowVersion = 0L)),
                expectedRowVersion = token,
                // Same key as the direct attempt above — the dispatcher replays
                // it from row.idempotencyKey.
                idempotencyKey = idempotencyKey,
            )
            ReplaceSplitsOutcome.Queued(projectOptimisticSplits(currentSplits, splits)) as ReplaceSplitsOutcome
        }
    }

    /**
     * Build the optimistic [ExpenseSplits] the server WOULD return once the
     * queued PUT replays: the user's edited rows + a recomputed total and
     * mismatch against the (unchanged) parent amount. Split timestamps are left
     * blank — they aren't surfaced in the editor and the server overwrites the
     * whole snapshot on replay. Member account names are carried over from the
     * current splits (or left blank for newly-added members the editor knows
     * about but the snapshot doesn't); the server re-resolves them on replay.
     */
    private fun projectOptimisticSplits(
        currentSplits: ExpenseSplits,
        drafts: List<ExpenseSplitDraft>,
    ): ExpenseSplits {
        val nameByMember = currentSplits.splits.associateBy({ it.memberId }, { it.accountName })
        val roleByMember = currentSplits.splits.associateBy({ it.memberId }, { it.role })
        val projected = drafts.mapIndexed { index, draft ->
            ExpenseSplit(
                publicId = "local-pending-$index",
                position = index,
                memberId = draft.memberId,
                accountName = nameByMember[draft.memberId].orEmpty(),
                role = roleByMember[draft.memberId] ?: "member",
                amountCents = draft.amountCents,
                note = draft.note,
                disabledAt = null,
                createdAt = "",
                updatedAt = "",
            )
        }
        val total = drafts.sumOf { it.amountCents }
        val parent = currentSplits.parentAmountCents
        val mismatch = parent?.let { total - it }
        return currentSplits.copy(
            splitsTotalAmountCents = total,
            mismatchCents = mismatch,
            splits = projected,
        )
    }

    suspend fun createNotificationDraft(
        draft: NotificationDraft,
        expectedLedgerId: String? = null,
    ): Result<Expense> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind(expectedLedgerId = expectedLedgerId)
        val created = bound.call { it.createNotificationDraft(draft.toRequest()) }
        created.toDomain()
    }

    suspend fun retryOcr(id: Long, expectedRowVersion: Long): Result<Expense> = core.errorHandler.safeCall {
        val bound = core.ledgerRequestGuard.bind()
        // ADR-0042: single-use key — direct-only path, no replay.
        val retried = bound.call {
            it.retryOcr(id, ExpenseStateTokenRequest(expectedRowVersion), UUID.randomUUID().toString())
        }
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
            // ADR-0042: one intent-time key for both the direct attempt and the
            // replay — see acknowledgeItemsMismatchAllowingOffline for rationale.
            val idempotencyKey = UUID.randomUUID().toString()
            try {
                val retried = bound.call {
                    it.retryOcr(expense.id, ExpenseStateTokenRequest(expense.rowVersion), idempotencyKey)
                }
                ExpenseStateOutcome.Synced(retried.toDomain()) as ExpenseStateOutcome
            } catch (networkError: IOException) {
                core.enqueueStateTransition(
                    bound = bound,
                    type = PendingMutationType.RetryOcr,
                    expense = expense,
                    networkError = networkError,
                    idempotencyKey = idempotencyKey,
                )
                ExpenseStateOutcome.Queued(expense) as ExpenseStateOutcome
            }
        }

    /**
     * ADR-0042 Slice E-2: offline-aware "粘贴文字识别". Body-carrying POST
     * (mirror of [replaceExpenseItemsAllowingOffline]) but the response is an
     * [Expense] (like retry-OCR), so it reuses [ExpenseStateOutcome].
     *  - direct 2xx → [ExpenseStateOutcome.Synced] with the server-parsed expense.
     *  - IOException → [ExpenseStateOutcome.Queued] with the expense UNCHANGED.
     *    Parsing happens server-side, so there's NOTHING to project optimistically
     *    offline — the UI tells the user it'll recognise on reconnect and the
     *    worker replays the recognize once connectivity returns.
     *  - HttpException → ``Result.failure``.
     *
     * Body-carrying (not the token-only [ExpenseRepositoryCore.enqueueStateTransition]
     * seam) because the queued row must persist the pasted ``raw_text``.
     */
    suspend fun recognizeTextAllowingOffline(
        expense: Expense,
        rawText: String,
    ): Result<ExpenseStateOutcome> = core.errorHandler.safeCall {
        if (!core.canModifyLedger()) {
            throw RepositoryException("当前角色为只读，无法修改账本。")
        }
        val bound = core.ledgerRequestGuard.bind()
        val request = ExpenseRecognizeTextRequestDto(
            expectedRowVersion = expense.rowVersion,
            rawText = rawText,
        )
        // ADR-0042: one intent-time key shared by the direct attempt and the
        // outbox replay. A committed-but-unseen POST (it commits server-side but
        // its response is lost) replays with this SAME key so the server HITs
        // the recorded success instead of false-409ing on the now-stale token.
        // The dispatcher replays it from row.idempotencyKey.
        val idempotencyKey = UUID.randomUUID().toString()
        try {
            val recognized = bound.call { it.recognizeText(expense.id, request, idempotencyKey) }.toDomain()
            ExpenseStateOutcome.Synced(recognized) as ExpenseStateOutcome
        } catch (networkError: IOException) {
            val outbox = core.outbox
            val adapter = core.recognizeTextAdapter
            val token = expense.rowVersion
            if (outbox == null || adapter == null || token == 0L) {
                // Outbox wiring missing OR baseline lacked a token — fall back
                // to the failure path so we don't pretend we recognised.
                throw networkError
            }
            // Session race guard: an IOException jumps past bound.call's
            // post-check, so re-assert the session before queuing (a row
            // queued under ledger A must not land in ledger B after a switch).
            bound.requireStillActive()
            // Strip the token from the payload — the row's expectedRowVersion is
            // the single source of truth; the dispatcher overwrites it on replay.
            // ``raw_text`` stays in the payload so the queued recognize replays
            // the user's pasted text.
            outbox.enqueue(
                type = PendingMutationType.RecognizeText,
                targetId = "expense:${expense.id}",
                payloadJson = adapter.toJson(request.copy(expectedRowVersion = 0L)),
                expectedRowVersion = token,
                // Same key as the direct attempt above — the dispatcher replays
                // it from row.idempotencyKey.
                idempotencyKey = idempotencyKey,
            )
            // Queued is the expense UNCHANGED — the server does the parsing.
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

/**
 * ADR-0042 Slice E-1 sealed result for
 * [ExpenseDetailRepository.replaceExpenseSplitsAllowingOffline]. Mirrors
 * [ReplaceItemsOutcome]: on [Synced] the splits are the server snapshot; on
 * [Queued] they are the optimistic projection of the user's edit (recomputed
 * total + mismatch), shown immediately while the queued PUT replays.
 */
sealed interface ReplaceSplitsOutcome {
    val splits: ExpenseSplits

    /** Server confirmed the replace; [splits] is the server snapshot. */
    data class Synced(override val splits: ExpenseSplits) : ReplaceSplitsOutcome

    /** Network failed; the replace is queued and [splits] is the optimistic projection. */
    data class Queued(override val splits: ExpenseSplits) : ReplaceSplitsOutcome
}

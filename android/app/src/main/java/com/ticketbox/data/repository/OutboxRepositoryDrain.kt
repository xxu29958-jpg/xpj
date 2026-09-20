package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationDao
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType

/**
 * Drain-side Room reads for [OutboxRepository].
 * The repository keeps the binding lease and passes an already-resolved binding.
 */

/**
 * Return the next runnable batch in causal order. Three filters:
 *
 * 1. Skip rows whose target has ANY unresolved sibling row —
 *    IN_FLIGHT (another drain is running it), CONFLICT (user
 *    hasn't picked keep/drop yet), or FAILED (waiting for
 *    manual retry or dismissal). [codex round-2 P1#1] fix:
 *    the old "only block on IN_FLIGHT" let a queued B sneak
 *    past a CONFLICT A and either fake-conflict or apply on
 *    top of an un-resolved state.
 * 2. Within the returned batch, keep only the OLDEST PENDING
 *    row per target. This is the [codex round-1 P1#1] fix —
 *    without per-target dedup, the same drain pass would
 *    return both A and B for ``expense:1`` and the engine
 *    would dispatch them in parallel even though
 *    ``markInFlightIfPending`` is per-row atomic. The DAO now
 *    also applies this same-target filter before ``LIMIT`` so
 *    duplicate targets do not consume the whole batch.
 * 3. Returns the public [OutboxRow] view (not the raw Entity)
 *    so the drain engine doesn't depend on Room types.
 */
internal suspend fun PendingMutationDao.nextRunnableRows(
    binding: OutboxBinding,
    unresolvedStatuses: List<String>,
    limit: Int,
    excludedIds: List<Long>,
): List<OutboxRow> {
    val candidates = nextRunnableBatch(
        ownerKey = binding.ownerStorageKey,
        ledgerId = binding.ledgerId,
        unresolvedStatuses = unresolvedStatuses,
        limit = limit,
        excludedIds = excludedIds,
    )
    if (candidates.isEmpty()) return emptyList()
    val seenTargets = mutableSetOf<String>()
    val runnable = mutableListOf<OutboxRow>()
    for (row in candidates) {
        if (!seenTargets.add(row.targetId)) {
            continue
        }
        runnable += row.toDomain()
    }
    return runnable
}

internal suspend fun PendingMutationDao.cascadePreservedTokens(
    binding: OutboxBinding,
    targetId: String,
    newToken: Long,
): Int = cascadeFreshTokenForTarget(
    ownerKey = binding.ownerStorageKey,
    ledgerId = binding.ledgerId,
    targetId = targetId,
    preservedTokenTypes = listOf(
        PendingMutationType.UndoExpense.wireValue,
        PendingMutationType.VoidExpenseOffset.wireValue,
        PendingMutationType.CreateBillSplitInvitation.wireValue,
        PendingMutationType.CorrectExpense.wireValue,
        PendingMutationType.CreateExpenseOffset.wireValue,
        PendingMutationType.UploadScreenshot.wireValue,
        PendingMutationType.OriginalAttachment.wireValue,
    ),
    freshToken = newToken,
)

internal suspend fun PendingMutationDao.reapExpiredPendingRows(cutoffIso: String): Int =
    markExpiredPendingAsFailed(
        cutoffCreatedAtIso = cutoffIso,
        status = PendingMutationStatus.Failed.wireValue,
        lastError = "outbox_row_expired",
    )

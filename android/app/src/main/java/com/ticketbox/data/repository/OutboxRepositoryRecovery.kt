package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.sync.withLock
import java.time.Instant
import java.util.UUID

/**
 * Clear, user recovery, and retention for [OutboxRepository].
 * Same-package physical move so the repository class stays under the LargeClass gate.
 */

/**
 * Drop every queued mutation. Used for explicit sign-out or
 * internal debug rebind paths where preserving offline edits
 * would keep private data after credentials are intentionally
 * removed. Ledger/server switches use [withBindingTransition]
 * instead; durable binding columns keep old rows from replaying
 * under the wrong session.
 *
 * @return the number of rows dropped.
 */
suspend fun OutboxRepository.clearAll(): Int {
    val removed = withBindingTransition(clearExistingRows = false) { dao.clearAll() }
    notifyRowsDeleted(removed)
    return removed
}

/** Remove only legacy or foreign-owner rows after explicit user confirmation. */
suspend fun OutboxRepository.clearQuarantined(): Int {
    val removed = dispatchLease.withLock {
        bindingTransitionLease.withLock {
            val binding = canonicalBindingWithAliasesMigratedLocked(bindingProvider())
            binding.requireReadyForEnqueue()
            dao.deleteQuarantined(binding.ownerStorageKey)
        }
    }
    if (removed > 0) notifyClearBoundary()
    notifyRowsDeleted(removed)
    return removed
}

/** Deletion is already committed. Cleanup runs outside either lease and cannot redefine that result. */
internal suspend fun OutboxRepository.notifyRowsDeleted(removed: Int) {
    if (removed <= 0) return
    try {
        onRowsDeleted()
    } catch (error: CancellationException) {
        throw error
    } catch (_: Exception) {
        // Keep unclaimed files for the next complete reference check; never infer another row deletion.
    }
}

internal fun OutboxRepository.notifyClearBoundary() {
    try {
        onClearAll()
    } catch (_: Exception) {
        // Best-effort scheduler cancel/re-arm signal. JVM-level
        // Errors still propagate; see [enqueue] for the same
        // Exception-not-Throwable rationale.
    }
}

internal suspend fun OutboxRepository.discardOriginalExpense(
    boundRequest: BoundLedgerRequest,
    row: OutboxRow,
    afterDeleted: suspend () -> Unit = {},
): Boolean = withActiveBinding(boundRequest) { binding ->
    check(row.type in setOf(PendingMutationType.CreateExpense, PendingMutationType.CorrectExpense) && row.status in setOf(
        PendingMutationStatus.Failed, PendingMutationStatus.Conflict, PendingMutationStatus.Done, PendingMutationStatus.Pending,
    ))
    check(row.type != PendingMutationType.CreateExpense || row.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict))
    check(row.ownerKey == binding.ownerStorageKey && row.ledgerId == binding.ledgerId)
    dao.deleteAndPublish(row.id, binding.ownerStorageKey, binding.ledgerId, row.status.wireValue, afterDeleted)
}.also { changed -> if (changed) { schedulePending(); if (row.type == PendingMutationType.CreateExpense) notifyRowsDeleted(1) } }

/**
 * User picked an action on a conflict-state row.
 *
 * - [ConflictResolution.KeepMine] refreshes the row's
 *   ``expected_row_version`` to the fresh token the call site
 *   just fetched and flips the row back to PENDING. Same
 *   ``id`` / ``createdAt``, so the queue order stays causal.
 * - [ConflictResolution.DropMine] permanently deletes the row.
 *   The user's local optimistic UI update should also be
 *   rolled back at the call site — that's not the outbox's
 *   job.
 */
internal suspend fun OutboxRepository.resolveConflict(id: Long, resolution: ConflictResolution, boundRequest: BoundLedgerRequest? = null): Boolean =
    resolveStatus(id, PendingMutationStatus.Conflict, resolution == ConflictResolution.DropMine,
        (resolution as? ConflictResolution.KeepMine)?.freshToken, boundRequest)

/**
 * User picked an action on a FAILED-state row.
 *
 * [codex round-3 P2#2] fix: FAILED rows block same-target later
 * mutations (see [dequeueNextRunnable]); without a user-facing
 * clear path a payload-parse fail or an unsupported-dispatcher
 * row would deadlock the rest of the queue for that target.
 *
 * - [FailedResolution.Retry] flips the row back to PENDING so
 *   the next drain re-claims it. If ``freshToken`` is supplied
 *   the row's ``expected_row_version`` is also refreshed.
 * - [FailedResolution.Drop] permanently deletes the row. The
 *   caller is responsible for rolling back any optimistic UI
 *   update that was tied to this mutation.
 */
internal suspend fun OutboxRepository.resolveFailed(id: Long, resolution: FailedResolution, boundRequest: BoundLedgerRequest? = null): Boolean =
    resolveStatus(id, PendingMutationStatus.Failed, resolution == FailedResolution.Drop,
        (resolution as? FailedResolution.Retry)?.freshToken, boundRequest)

/** A command owner has reviewed this unverified completed original; remove only its local record. */
internal suspend fun OutboxRepository.discardCompletedOriginalSubmission(boundRequest: BoundLedgerRequest, row: OutboxRow): Boolean {
    require(row.type in setOf(PendingMutationType.CreateIncomePlan, PendingMutationType.UpdateIncomePlan,
        PendingMutationType.SaveManualExchangeRate))
    require(row.status == PendingMutationStatus.Done)
    boundRequest.requireStillActiveFor(requireNotNull(row.bindingOrNull()))
    return resolveStatus(row.id, PendingMutationStatus.Done, true, null, boundRequest)
}

/** One status-checked recovery owner; only an actual replay or deletion wakes successors. */
private suspend fun OutboxRepository.resolveStatus(id: Long, status: PendingMutationStatus, drop: Boolean, freshToken: Long?, boundRequest: BoundLedgerRequest? = null): Boolean {
    val requeue = if (status == PendingMutationStatus.Conflict) dao::requeueConflictWithFreshToken
        else dao::requeueFailedWithFreshToken
    var expired = false
    val changed = bindingTransitionLease.withLock {
        val binding = canonicalBindingWithAliasesMigratedLocked(bindingProvider())
        boundRequest?.requireStillActiveFor(binding)
        if (!drop && dao.refusesExpenseRecovery(binding, id, status, freshToken)) return@withLock false
        when {
            drop -> dao.deleteIfStatus(id, binding.ownerStorageKey, binding.ledgerId, status.wireValue) > 0
            expireOverAgeOnResolve(id, binding, status.wireValue) -> {
                expired = true
                true
            }
            freshToken != null -> requeue(id, binding.ownerStorageKey, binding.ledgerId,
                freshToken, UUID.randomUUID().toString()) > 0
            else -> dao.retryFailed(id, binding.ownerStorageKey, binding.ledgerId, NON_RETRYABLE_UPLOAD_ERRORS) > 0
        }
    }
    if (changed && !expired) schedulePending()
    if (changed && drop) notifyRowsDeleted(1)
    return changed
}
/**
 * Garbage-collect completed DONE rows older than [retentionMillis].
 *
 * FAILED rows are unresolved user-action rows, not retention
 * artifacts. They stay until the user retries or drops them; this
 * keeps a future DAO refactor from silently deleting failed local
 * mutations after seven days.
 */
suspend fun OutboxRepository.gcCompleted(retentionMillis: Long = OutboxRepository.DEFAULT_RETENTION_MS): Int {
    val cutoff = Instant.now(clock).minusMillis(retentionMillis)
    val removed = dao.deleteResolvedBefore(
        doneStatus = PendingMutationStatus.Done.wireValue,
        cutoffIso = OutboxRepository.ISO.format(cutoff),
    )
    notifyRowsDeleted(removed)
    return removed
}
/**
 * ADR-0042 §4.10 resolve-time age guard. The reaper ([reapExpiredPending]) only
 * touches PENDING rows, so a FAILED / CONFLICT row awaiting the user past the
 * age cap never carries the ``outbox_row_expired`` marker. Retry / KeepMine
 * would flip it to PENDING with its original ``createdAt`` → the next drain's
 * reaper instantly re-expires it (a dead action), and replaying risks
 * double-apply (a rotated/fresh token can't undo a committed-but-unseen
 * original whose ~30d-retention server key was purged). Expires the row
 * (terminal) iff it's still in [fromStatus] AND over-age; returns true if it
 * fired so the resolve path skips the normal flip-to-PENDING. Uses the repo's
 * own [clock] — this is the user-action path, not the engine's drain clock.
 */
internal suspend fun OutboxRepository.expireOverAgeOnResolve(
    id: Long,
    binding: OutboxBinding,
    fromStatus: String,
): Boolean {
    val cutoff = OutboxRepository.ISO.format(Instant.now(clock).minusMillis(OUTBOX_PENDING_AGE_CAP_MILLIS))
    return dao.expireBoundRowIfStatusAndOverAge(
        id = id,
        ownerKey = binding.ownerStorageKey,
        ledgerId = binding.ledgerId,
        fromStatus = fromStatus,
        cutoffCreatedAtIso = cutoff,
    ) > 0
}


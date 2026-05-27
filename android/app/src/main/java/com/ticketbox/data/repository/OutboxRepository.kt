package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationDao
import com.ticketbox.data.local.PendingMutationEntity
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import java.time.Clock
import java.time.Instant
import java.time.format.DateTimeFormatter

/**
 * ADR-0038 PR-2f: offline outbox skeleton.
 *
 * This repository is the queue surface every mutation call site
 * uses when going offline. PR-2f intentionally does NOT wire the
 * mutation call sites — those edits land in PR-2g together with
 * the WorkManager drain worker and the conflict-banner UI. Keeping
 * the skeleton landable in isolation lets reviewers focus on the
 * Room schema migration and the queue semantics without also
 * weighing the call-site changes.
 *
 * Concurrency contract enforced here:
 * 1. [enqueue] takes a snapshot of the mutation; the call site
 *    must already have applied the optimistic UI update before
 *    calling — the outbox is durable storage, not the UI source
 *    of truth.
 * 2. Drain happens in [dequeueNextRunnable] which respects "same
 *    target_id serial": a row is skipped if another row for the
 *    same target is currently IN_FLIGHT. PR-2g's worker calls
 *    this in a loop.
 * 3. [resolveConflict] is the user-facing "keep mine / drop mine"
 *    branch. ``keepMine`` re-enqueues with a fresh token (caller
 *    fetched the row again); ``dropMine`` deletes the row.
 *
 * The repository is intentionally Moshi-free: payloads land as
 * already-serialised JSON strings, so a future mutation type can
 * be added without touching this layer.
 */
class OutboxRepository(
    private val dao: PendingMutationDao,
    private val clock: Clock = Clock.systemUTC(),
) {

    /**
     * Persist a mutation snapshot for later replay.
     *
     * @return the row id of the freshly inserted outbox entry.
     */
    suspend fun enqueue(
        type: PendingMutationType,
        targetId: String,
        payloadJson: String,
        expectedUpdatedAt: String,
    ): Long {
        val row = PendingMutationEntity(
            type = type.wireValue,
            targetId = targetId,
            payload = payloadJson,
            expectedUpdatedAt = expectedUpdatedAt,
            status = PendingMutationStatus.Pending.wireValue,
            createdAt = nowIso(),
        )
        return dao.insert(row)
    }

    /**
     * Return the next runnable batch in causal order. Rows whose
     * target is already IN_FLIGHT are filtered out so the drain
     * worker doesn't violate "same target_id serial".
     *
     * Returns the public [OutboxRow] view (not the raw Entity) so
     * the drain engine doesn't depend on Room types.
     */
    suspend fun dequeueNextRunnable(limit: Int = DEFAULT_DRAIN_BATCH): List<OutboxRow> {
        val candidates = dao.nextPendingBatch(PendingMutationStatus.Pending.wireValue, limit)
        if (candidates.isEmpty()) return emptyList()
        val runnable = mutableListOf<OutboxRow>()
        for (row in candidates) {
            if (!dao.isTargetBusy(row.targetId, PendingMutationStatus.InFlight.wireValue)) {
                runnable += row.toDomain()
            }
        }
        return runnable
    }

    suspend fun markInFlight(id: Long) {
        dao.markInFlight(
            id = id,
            status = PendingMutationStatus.InFlight.wireValue,
            attemptedAt = nowIso(),
        )
    }

    suspend fun markDone(id: Long) {
        dao.markDone(
            id = id,
            status = PendingMutationStatus.Done.wireValue,
            completedAt = nowIso(),
        )
    }

    suspend fun markConflict(id: Long, serverMessage: String) {
        dao.markConflict(
            id = id,
            status = PendingMutationStatus.Conflict.wireValue,
            lastError = serverMessage,
        )
    }

    suspend fun markFailed(id: Long, error: String) {
        dao.markFailed(
            id = id,
            status = PendingMutationStatus.Failed.wireValue,
            lastError = error,
        )
    }

    /**
     * User picked an action on a conflict-state row.
     *
     * - [ConflictResolution.KeepMine] refreshes the row's
     *   ``expected_updated_at`` to the fresh token the call site
     *   just fetched and flips the row back to PENDING. Same
     *   ``id`` / ``createdAt``, so the queue order stays causal.
     * - [ConflictResolution.DropMine] permanently deletes the row.
     *   The user's local optimistic UI update should also be
     *   rolled back at the call site — that's not the outbox's
     *   job.
     */
    suspend fun resolveConflict(
        id: Long,
        resolution: ConflictResolution,
    ) {
        when (resolution) {
            is ConflictResolution.KeepMine ->
                dao.refreshToken(
                    id = id,
                    pendingStatus = PendingMutationStatus.Pending.wireValue,
                    freshToken = resolution.freshToken,
                )
            ConflictResolution.DropMine ->
                dao.deleteById(id)
        }
    }

    /**
     * Live queue-depth surface for the global "你有 N 笔待同步"
     * status pill.
     */
    fun observeQueueDepth(): Flow<Int> =
        dao.observeQueueDepth(
            PendingMutationStatus.Pending.wireValue,
            PendingMutationStatus.InFlight.wireValue,
        )

    /**
     * Live stream of rows in CONFLICT state. The conflict-banner
     * UI in PR-2g subscribes to this and renders one banner per
     * row with "keep mine / drop mine" buttons.
     *
     * Status string is converted back to the enum on read so the
     * UI layer doesn't have to know wire values.
     */
    fun observeConflicts(): Flow<List<OutboxRow>> =
        dao.observeConflictRows(PendingMutationStatus.Conflict.wireValue)
            .map { rows -> rows.map { it.toDomain() } }

    suspend fun activeForTarget(targetId: String): List<OutboxRow> =
        dao.activeForTarget(
            targetId = targetId,
            pendingStatus = PendingMutationStatus.Pending.wireValue,
            inFlightStatus = PendingMutationStatus.InFlight.wireValue,
            conflictStatus = PendingMutationStatus.Conflict.wireValue,
            failedStatus = PendingMutationStatus.Failed.wireValue,
        ).map { it.toDomain() }

    /**
     * Garbage-collect terminal rows older than [retentionMillis].
     * Called from a cleanup tick (PR-2g wires it to WorkManager).
     */
    suspend fun gcCompleted(retentionMillis: Long = DEFAULT_RETENTION_MS): Int {
        val cutoff = Instant.now(clock).minusMillis(retentionMillis)
        return dao.deleteResolvedBefore(
            doneStatus = PendingMutationStatus.Done.wireValue,
            failedStatus = PendingMutationStatus.Failed.wireValue,
            cutoffIso = ISO.format(cutoff),
        )
    }

    private fun nowIso(): String = ISO.format(Instant.now(clock))

    companion object {
        private val ISO: DateTimeFormatter = DateTimeFormatter.ISO_INSTANT

        const val DEFAULT_DRAIN_BATCH: Int = 25
        /** 7 days — enough to power undo / audit and not enough to
         *  let the DB grow unbounded on a phone. */
        const val DEFAULT_RETENTION_MS: Long = 7L * 24L * 60L * 60L * 1000L
    }
}

/**
 * Public outbox row view. Decouples UI / VM code from the Room
 * Entity so renaming a column doesn't break callers.
 */
data class OutboxRow(
    val id: Long,
    val type: PendingMutationType,
    val targetId: String,
    val payloadJson: String,
    val expectedUpdatedAt: String,
    val status: PendingMutationStatus,
    val retryCount: Int,
    val lastError: String?,
    val createdAt: String,
    val attemptedAt: String?,
    val completedAt: String?,
)

private fun PendingMutationEntity.toDomain(): OutboxRow = OutboxRow(
    id = id,
    type = PendingMutationType.fromWire(type),
    targetId = targetId,
    payloadJson = payload,
    expectedUpdatedAt = expectedUpdatedAt,
    status = PendingMutationStatus.fromWire(status),
    retryCount = retryCount,
    lastError = lastError,
    createdAt = createdAt,
    attemptedAt = attemptedAt,
    completedAt = completedAt,
)

/**
 * User-facing branch on a CONFLICT row. The "keep mine" branch
 * needs a freshly-fetched token from the call site (the previous
 * one is by definition stale).
 */
sealed interface ConflictResolution {
    data class KeepMine(val freshToken: String) : ConflictResolution
    data object DropMine : ConflictResolution
}

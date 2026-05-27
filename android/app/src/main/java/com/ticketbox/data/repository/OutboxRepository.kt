package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationDao
import com.ticketbox.data.local.PendingMutationEntity
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
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
 *    same target is currently IN_FLIGHT / CONFLICT / FAILED. The
 *    SQL filter ([PendingMutationDao.nextRunnableBatch]) excludes
 *    blocked targets BEFORE applying ``LIMIT`` so a long PENDING
 *    queue for a blocked target doesn't starve other runnable
 *    targets. PR-2g's worker calls this in a loop.
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
     *    ``markInFlightIfPending`` is per-row atomic.
     * 3. Returns the public [OutboxRow] view (not the raw Entity)
     *    so the drain engine doesn't depend on Room types.
     */
    suspend fun dequeueNextRunnable(limit: Int = DEFAULT_DRAIN_BATCH): List<OutboxRow> {
        // [codex round-3 P2#1 / round-4 P1] Use the SQL-side filter
        // so LIMIT applies AFTER unresolved targets are excluded.
        // Round-3 introduced ``nextRunnableBatch`` but a rebase wiped
        // out the production caller; round-4 wires it back.
        val candidates = dao.nextRunnableBatch(
            pendingStatus = PendingMutationStatus.Pending.wireValue,
            inFlightStatus = PendingMutationStatus.InFlight.wireValue,
            conflictStatus = PendingMutationStatus.Conflict.wireValue,
            failedStatus = PendingMutationStatus.Failed.wireValue,
            limit = limit,
        )
        if (candidates.isEmpty()) return emptyList()
        val seenTargets = mutableSetOf<String>()
        val runnable = mutableListOf<OutboxRow>()
        for (row in candidates) {
            if (!seenTargets.add(row.targetId)) {
                // An older PENDING row for this target is already
                // in the batch; the second one waits for the next
                // drain pass to keep "same target serial".
                continue
            }
            runnable += row.toDomain()
        }
        return runnable
    }

    /**
     * Recovery: push rows stuck in IN_FLIGHT past [staleAfterMillis]
     * back to PENDING so the next drain can re-claim them. Called
     * by the engine at the start of each drain.
     *
     * [codex round-2 P1#2] fix: a CancellationException after
     * ``tryClaim`` succeeded leaves the row IN_FLIGHT; without
     * this sweep ``hasUnresolvedRowForTarget`` then blocks every
     * later sibling forever.
     */
    suspend fun recoverStaleInFlight(staleAfterMillis: Long = DEFAULT_STALE_IN_FLIGHT_MS): Int {
        val cutoff = Instant.now(clock).minusMillis(staleAfterMillis)
        return dao.recoverStaleInFlight(
            pendingStatus = PendingMutationStatus.Pending.wireValue,
            inFlightStatus = PendingMutationStatus.InFlight.wireValue,
            staleCutoffIso = ISO.format(cutoff),
            recoveryMessage = "recovered_from_stuck_in_flight",
        )
    }

    /**
     * Atomic PENDING → IN_FLIGHT claim. Returns ``true`` if this
     * caller won the race and is now responsible for dispatching;
     * ``false`` means another drain pass already claimed it and
     * the caller must NOT call the ApiService.
     */
    suspend fun tryClaim(id: Long): Boolean {
        val rowcount = dao.markInFlightIfPending(
            id = id,
            fromStatus = PendingMutationStatus.Pending.wireValue,
            inFlightStatus = PendingMutationStatus.InFlight.wireValue,
            attemptedAt = nowIso(),
        )
        return rowcount > 0
    }

    suspend fun markDone(id: Long) {
        dao.markDone(
            id = id,
            status = PendingMutationStatus.Done.wireValue,
            completedAt = nowIso(),
        )
    }

    /**
     * Cascade a freshly-server-returned token to every PENDING row
     * targeting the same row. See
     * [PendingMutationDao.cascadeFreshTokenForTarget] for the why.
     *
     * Returns the count of cascaded rows for tests / telemetry.
     */
    suspend fun cascadeFreshToken(targetId: String, newToken: String): Int =
        dao.cascadeFreshTokenForTarget(
            targetId = targetId,
            pendingStatus = PendingMutationStatus.Pending.wireValue,
            freshToken = newToken,
        )

    /**
     * Transient failure: keep the row in PENDING so the next drain
     * pass picks it up. ``retryCount`` was already bumped by
     * [tryClaim]; the back-off / give-up policy belongs to the
     * scheduler in PR-2g.2.
     */
    suspend fun markRetryable(id: Long, error: String) {
        dao.markRetryable(
            id = id,
            pendingStatus = PendingMutationStatus.Pending.wireValue,
            lastError = error,
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
    ): Boolean {
        // [codex round-4 P2] Atomic status-checked updates so a
        // stale UI banner click can't flip a DONE / re-resolved row
        // back to PENDING (or delete a row a parallel keep-mine
        // just turned PENDING). Returns ``true`` only if THIS call
        // actually changed the row.
        return when (resolution) {
            is ConflictResolution.KeepMine ->
                dao.refreshTokenIfStatus(
                    id = id,
                    fromStatus = PendingMutationStatus.Conflict.wireValue,
                    toStatus = PendingMutationStatus.Pending.wireValue,
                    freshToken = resolution.freshToken,
                ) > 0
            ConflictResolution.DropMine ->
                dao.deleteIfStatus(
                    id = id,
                    expectedStatus = PendingMutationStatus.Conflict.wireValue,
                ) > 0
        }
    }

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
     *   the row's ``expected_updated_at`` is also refreshed.
     * - [FailedResolution.Drop] permanently deletes the row. The
     *   caller is responsible for rolling back any optimistic UI
     *   update that was tied to this mutation.
     */
    suspend fun resolveFailed(
        id: Long,
        resolution: FailedResolution,
    ): Boolean {
        // [codex round-4 P2] Same atomic-status guard as
        // resolveConflict — stale banner click on a row that's
        // already been retried + DONE elsewhere must be a no-op.
        return when (resolution) {
            is FailedResolution.Retry -> {
                val freshToken = resolution.freshToken
                if (freshToken != null) {
                    dao.refreshTokenIfStatus(
                        id = id,
                        fromStatus = PendingMutationStatus.Failed.wireValue,
                        toStatus = PendingMutationStatus.Pending.wireValue,
                        freshToken = freshToken,
                    ) > 0
                } else {
                    dao.markRetryableIfStatus(
                        id = id,
                        fromStatus = PendingMutationStatus.Failed.wireValue,
                        toStatus = PendingMutationStatus.Pending.wireValue,
                        lastError = "manual retry",
                    ) > 0
                }
            }
            FailedResolution.Drop ->
                dao.deleteIfStatus(
                    id = id,
                    expectedStatus = PendingMutationStatus.Failed.wireValue,
                ) > 0
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

    /**
     * Live stream of FAILED rows for the "manual retry / drop"
     * banner. Counterpart of [observeConflicts]; both states block
     * same-target later mutations and need a UI surface to clear.
     */
    fun observeFailed(): Flow<List<OutboxRow>> =
        dao.observeFailedRows(PendingMutationStatus.Failed.wireValue)
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
        /**
         * Fixed-width UTC timestamp formatter used everywhere outbox
         * writes a time to a TEXT column.
         *
         * [codex round-6 P2] fix: SQLite compares TEXT columns
         * lexicographically. ``DateTimeFormatter.ISO_INSTANT`` is
         * variable-width — it omits fractional seconds when they're
         * zero, so ``2026-05-04T12:00:00.001Z`` (later in time)
         * actually sorts BEFORE ``2026-05-04T12:00:00Z`` because
         * ``'.'`` (0x2E) < ``'Z'`` (0x5A). That breaks
         * ``ORDER BY createdAt`` causality AND breaks the
         * ``recoverStaleInFlight`` cutoff comparison.
         *
         * Fixed width (always ``yyyy-MM-ddTHH:mm:ss.SSS'Z'``, 24
         * chars) makes lex order == time order.
         */
        private val ISO: DateTimeFormatter = DateTimeFormatter
            .ofPattern("uuuu-MM-dd'T'HH:mm:ss.SSS'Z'")
            .withZone(ZoneOffset.UTC)

        const val DEFAULT_DRAIN_BATCH: Int = 25
        /** 7 days — enough to power undo / audit and not enough to
         *  let the DB grow unbounded on a phone. */
        const val DEFAULT_RETENTION_MS: Long = 7L * 24L * 60L * 60L * 1000L
        /** 5 minutes — any IN_FLIGHT older than this is presumed
         *  abandoned by a cancelled / dead worker and is swept
         *  back to PENDING at next drain start. */
        const val DEFAULT_STALE_IN_FLIGHT_MS: Long = 5L * 60L * 1000L
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

/**
 * User-facing branch on a FAILED row. Unlike [ConflictResolution]
 * the fresh token is optional — most FAILED rows are payload-parse
 * errors or unsupported-dispatcher rows where re-fetching server
 * state isn't meaningful; the user is just deciding "try again on
 * an upgraded build" vs "give up".
 */
sealed interface FailedResolution {
    data class Retry(val freshToken: String? = null) : FailedResolution
    data object Drop : FailedResolution
}

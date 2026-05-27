package com.ticketbox.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

/**
 * ADR-0038 PR-2f outbox DAO.
 *
 * Read-side responsibilities:
 *   - [nextPendingBatch] is the drain worker's queue: returns rows
 *     in ``createdAt`` ASC order so older mutations replay first,
 *     enforcing causality.
 *   - [isTargetBusy] / [activeForTarget] let the drain worker check
 *     "is another mutation for this target already IN_FLIGHT" before
 *     dequeuing a new one — same-target serial requirement from the
 *     ADR.
 *   - [observeQueueDepth] / [observeConflictRows] feed the conflict-
 *     banner UI in PR-2g; both are Flow so the UI re-renders without
 *     polling.
 *
 * Write-side responsibilities:
 *   - [enqueue] is fire-and-forget from the mutation call sites.
 *   - [markInFlight] / [markDone] / [markConflict] / [markFailed]
 *     are the drain worker's status transitions.
 *   - [refreshToken] lets the "keep mine" branch re-enqueue with a
 *     freshly-fetched ``expected_updated_at`` without writing a new
 *     row, preserving the original ``createdAt`` so the queue order
 *     stays causal.
 *   - [deleteResolved] is the cleanup pruner — terminal rows older
 *     than the retention window go away.
 *
 * Why a single DAO instead of a Repository: the outbox surface is
 * small and the Repository in PR-2g will compose DAO calls with
 * Moshi adapters and the ApiService call. Splitting now would just
 * push trivial pass-through methods up a layer.
 */
@Dao
interface PendingMutationDao {

    // ---------------------------------------------------------------
    // Enqueue / status writes
    // ---------------------------------------------------------------

    @Insert(onConflict = OnConflictStrategy.ABORT)
    suspend fun insert(row: PendingMutationEntity): Long

    @Query(
        """
        UPDATE pending_mutations
        SET status = :status,
            attemptedAt = :attemptedAt,
            retryCount = retryCount + 1
        WHERE id = :id
        """,
    )
    suspend fun markInFlight(id: Long, status: String, attemptedAt: String): Int

    @Query(
        """
        UPDATE pending_mutations
        SET status = :status,
            completedAt = :completedAt,
            lastError = NULL
        WHERE id = :id
        """,
    )
    suspend fun markDone(id: Long, status: String, completedAt: String): Int

    @Query(
        """
        UPDATE pending_mutations
        SET status = :status,
            lastError = :lastError
        WHERE id = :id
        """,
    )
    suspend fun markConflict(id: Long, status: String, lastError: String): Int

    @Query(
        """
        UPDATE pending_mutations
        SET status = :status,
            lastError = :lastError
        WHERE id = :id
        """,
    )
    suspend fun markFailed(id: Long, status: String, lastError: String): Int

    @Query(
        """
        UPDATE pending_mutations
        SET status = :pendingStatus,
            expectedUpdatedAt = :freshToken,
            lastError = NULL
        WHERE id = :id
        """,
    )
    suspend fun refreshToken(id: Long, pendingStatus: String, freshToken: String): Int

    // ---------------------------------------------------------------
    // Reads (drain + UI)
    // ---------------------------------------------------------------

    /**
     * Drain worker entry point: oldest pending rows first, capped at
     * [limit]. ``createdAt`` ascending preserves the order in which
     * the user issued the mutations.
     *
     * The drain worker must additionally apply [isTargetBusy] before
     * dequeuing — Room can't express "skip rows whose target is
     * already IN_FLIGHT" as a single query without inflating the
     * schema, and we'd rather keep the DAO declarative.
     */
    @Query(
        """
        SELECT * FROM pending_mutations
        WHERE status = :pendingStatus
        ORDER BY createdAt ASC, id ASC
        LIMIT :limit
        """,
    )
    suspend fun nextPendingBatch(pendingStatus: String, limit: Int): List<PendingMutationEntity>

    /**
     * True if another row for the same target is currently
     * ``IN_FLIGHT``. PR-2g's drain worker calls this to enforce
     * "same target_id serial" without holding a global drain lock.
     */
    @Query(
        """
        SELECT COUNT(*) > 0 FROM pending_mutations
        WHERE targetId = :targetId
          AND status = :inFlightStatus
        """,
    )
    suspend fun isTargetBusy(targetId: String, inFlightStatus: String): Boolean

    /**
     * Returns all non-terminal rows for a given target — useful for
     * the conflict-banner UI when the user opens the affected row's
     * detail page.
     */
    @Query(
        """
        SELECT * FROM pending_mutations
        WHERE targetId = :targetId
          AND status IN (:pendingStatus, :inFlightStatus, :conflictStatus, :failedStatus)
        ORDER BY createdAt ASC, id ASC
        """,
    )
    suspend fun activeForTarget(
        targetId: String,
        pendingStatus: String,
        inFlightStatus: String,
        conflictStatus: String,
        failedStatus: String,
    ): List<PendingMutationEntity>

    /**
     * Live queue depth for the global "你有 N 笔待同步" status pill.
     * Counts only rows still actively traveling through the queue
     * (PENDING / IN_FLIGHT) — conflicts and failures need user
     * action and are surfaced separately.
     */
    @Query(
        """
        SELECT COUNT(*) FROM pending_mutations
        WHERE status IN (:pendingStatus, :inFlightStatus)
        """,
    )
    fun observeQueueDepth(pendingStatus: String, inFlightStatus: String): Flow<Int>

    /**
     * Live stream of rows the user needs to resolve. Drives the
     * conflict-banner UI in PR-2g.
     */
    @Query(
        """
        SELECT * FROM pending_mutations
        WHERE status = :conflictStatus
        ORDER BY createdAt ASC, id ASC
        """,
    )
    fun observeConflictRows(conflictStatus: String): Flow<List<PendingMutationEntity>>

    /**
     * Delete by id. Used when the user picks "drop mine" on a
     * conflict, or when cleanup runs.
     */
    @Query("DELETE FROM pending_mutations WHERE id = :id")
    suspend fun deleteById(id: Long): Int

    /**
     * Prune terminal-state rows older than [cutoffIso] (ISO-Z).
     * Called by the cleanup path on app start / on a scheduled
     * background tick.
     */
    @Query(
        """
        DELETE FROM pending_mutations
        WHERE status IN (:doneStatus, :failedStatus)
          AND completedAt IS NOT NULL
          AND completedAt < :cutoffIso
        """,
    )
    suspend fun deleteResolvedBefore(
        doneStatus: String,
        failedStatus: String,
        cutoffIso: String,
    ): Int
}

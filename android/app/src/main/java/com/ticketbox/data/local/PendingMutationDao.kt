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
 *   - [nextRunnableBatch] is the drain worker's queue: returns
 *     PENDING rows in ``createdAt`` ASC order, excluding any row
 *     whose target already has an unresolved sibling (IN_FLIGHT /
 *     CONFLICT / FAILED). The exclusion is in SQL (``NOT EXISTS``)
 *     so ``LIMIT`` applies AFTER blocked targets are skipped.
 *   - [nextPendingBatch] is a simpler PENDING-only pull used by
 *     tests and the stale-IN_FLIGHT recovery sweep, neither of
 *     which needs the unresolved-target filter.
 *   - [hasUnresolvedRowForTarget] / [activeForTarget] / [isTargetBusy]
 *     let the repository check target state for cascade / banner
 *     queries.
 *   - [observeQueueDepth] / [observeConflictRows] / [observeFailedRows]
 *     feed the queue-depth pill + the conflict and FAILED banners
 *     in PR-2g; all Flow so the UI re-renders without polling.
 *
 * Write-side responsibilities:
 *   - [insert] is fire-and-forget from the mutation call sites.
 *   - [markInFlightIfPending] / [markDone] / [markConflict] /
 *     [markFailed] / [markRetryable] are the drain worker's status
 *     transitions. ``IfPending`` and the ``...IfStatus`` family
 *     all carry a ``status = :fromStatus`` predicate so concurrent
 *     drains / stale UI banners can't move a row out of the state
 *     the caller thought it was in.
 *   - [refreshTokenIfStatus] / [markRetryableIfStatus] /
 *     [deleteIfStatus] are the user-facing resolveConflict /
 *     resolveFailed building blocks; each is rowcount-checked so
 *     a stale banner click is a no-op rather than a stomp.
 *   - [cascadeFreshTokenForTarget] propagates a server-returned
 *     ``updated_at`` to other PENDING rows of the same target
 *     after a successful dispatch.
 *   - [recoverStaleInFlight] / [deleteResolvedBefore] are the
 *     periodic cleanup operations.
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

    /**
     * Atomic claim: flip a row to IN_FLIGHT only when it's still
     * PENDING. ``rowcount = 0`` means another drain pass already
     * grabbed this row; the caller MUST not dispatch in that case.
     *
     * [codex finding P1#2] fix: without the ``status = :fromStatus``
     * predicate, two concurrent drains (two WorkManager workers, a
     * UI-triggered drain plus a periodic one, etc) both read the
     * same PENDING row from ``nextPendingBatch`` and both call
     * ``markInFlight``, then both fire the ApiService request.
     */
    @Query(
        """
        UPDATE pending_mutations
        SET status = :inFlightStatus,
            attemptedAt = :attemptedAt,
            retryCount = retryCount + 1
        WHERE id = :id AND status = :fromStatus
        """,
    )
    suspend fun markInFlightIfPending(
        id: Long,
        fromStatus: String,
        inFlightStatus: String,
        attemptedAt: String,
    ): Int

    /**
     * Move a row back to PENDING after a transient failure
     * ([DispatchResult.RetryableFailure]). Preserves the retry
     * counter that ``markInFlightIfPending`` bumped (so callers
     * can apply back-off based on it) and records the error so
     * the UI can hint after repeated attempts.
     */
    @Query(
        """
        UPDATE pending_mutations
        SET status = :pendingStatus,
            lastError = :lastError
        WHERE id = :id
        """,
    )
    suspend fun markRetryable(
        id: Long,
        pendingStatus: String,
        lastError: String,
    ): Int

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

    /**
     * ADR-0042 §4.10 reaper: flip every still-PENDING row enqueued before
     * [cutoffCreatedAtIso] to a terminal status WITHOUT replaying it. Returns the
     * rowcount so the repository can report how many rows it reaped.
     *
     * Why this exists (the double-apply hazard): a PENDING row's
     * ``idempotencyKey`` is only honoured by the server while the matching key
     * is still in ``api_idempotency_keys`` (~30-day retention). A row that's been
     * PENDING longer than that would, on replay, hit a server that has forgotten
     * the key → the server treats it as a NEW request → the mutation applies a
     * second time. Reaping the row (terminal status, never dispatched) before the
     * key could expire is the only safe outcome; the user redoes the action
     * against fresh server state. See [OUTBOX_PENDING_AGE_CAP_MILLIS] for the
     * margin rationale.
     *
     * **Cutoff is an ISO-Z string, not millis** — ``createdAt`` is a fixed-width
     * ISO TEXT column (see [OutboxRepository.ISO]) that SQLite compares
     * lexicographically; a numeric cutoff would not compare meaningfully against
     * it. The repository converts ``now - cap`` to the same fixed-width format,
     * exactly like [recoverStaleInFlight]'s ``staleCutoffIso`` and
     * [deleteResolvedBefore]'s ``cutoffIso``.
     *
     * Intentionally **not binding-scoped** (no ``serverUrl`` / ``ledgerId``
     * filter, unlike the drain reads): a stale PENDING row under ANY binding is a
     * double-apply risk the moment that binding becomes active again, so the
     * reaper must catch all of them — same global reach as the
     * [deleteResolvedBefore] / [clearAll] DAO ops. The ``status = 'pending'``
     * guard means only un-dispatched rows are affected; IN_FLIGHT / CONFLICT /
     * FAILED / DONE rows are never touched (a CONFLICT/FAILED row is already
     * awaiting the user, and an IN_FLIGHT row is mid-send).
     */
    @Query(
        """
        UPDATE pending_mutations
        SET status = :status,
            lastError = :lastError
        WHERE status = 'pending'
          AND createdAt < :cutoffCreatedAtIso
        """,
    )
    suspend fun markExpiredPendingAsFailed(
        cutoffCreatedAtIso: String,
        status: String,
        lastError: String,
    ): Int

    /**
     * ADR-0042 §4.10 resolve-time age guard. The reaper ([markExpiredPendingAsFailed])
     * only touches PENDING rows, so a FAILED (``max_attempts_exceeded``) or CONFLICT
     * row that's been awaiting the user past the age cap never gets the
     * ``outbox_row_expired`` marker. Retrying / keep-mine-ing such a row flips it to
     * PENDING with its ORIGINAL ``createdAt``, so the very next drain's reaper
     * re-expires it — a dead action that also risks double-apply (a rotated key
     * doesn't save a committed-but-unseen original whose key the server has purged).
     * This atomically expires the row (terminal, never re-queued) iff it's still in
     * [fromStatus] AND already over-age, so the resolve path defers to the same
     * cutoff the reaper uses. Returns rowcount so the repo can short-circuit the
     * normal re-queue when this fired.
     */
    @Query(
        """
        UPDATE pending_mutations
        SET status = :expiredStatus,
            lastError = :lastError
        WHERE id = :id
          AND status = :fromStatus
          AND createdAt < :cutoffCreatedAtIso
        """,
    )
    suspend fun expireIfStatusAndOverAge(
        id: Long,
        fromStatus: String,
        cutoffCreatedAtIso: String,
        expiredStatus: String,
        lastError: String,
    ): Int

    @Query(
        """
        UPDATE pending_mutations
        SET status = :pendingStatus,
            expectedRowVersion = :freshToken,
            lastError = NULL
        WHERE id = :id
        """,
    )
    suspend fun refreshToken(id: Long, pendingStatus: String, freshToken: Long): Int

    /**
     * Atomic ``CONFLICT → PENDING`` or ``FAILED → PENDING`` token refresh used by
     * both [OutboxRepository.resolveConflict] (``KeepMine``) and
     * [OutboxRepository.resolveFailed] (``Retry(freshToken=...)``). The
     * ``status = fromStatus`` predicate makes the call a no-op if the row already
     * advanced (e.g. the user clicked "keep mine" twice on a stale banner after
     * a different surface already resolved it). Returns the affected rowcount so
     * the repository can branch on it.
     *
     * codex P1 #7: ``retryCount = 0`` 重置——两条路径都是用户显式"重试", 都该拿到完整
     * 的 max_attempts 预算, 而不是接着之前的失败次数继续撞 cap。
     *
     * [codex round-4 P2] fix: prevents a stale UI banner from
     * flipping a DONE / dropped row back to PENDING.
     *
     * ADR-0042 §4.8: refreshing ``expectedRowVersion`` is the "overwrite the new
     * server version after seeing the conflict/failure" NEW intent, so a
     * key-bearing row (PatchExpense) must ROTATE its ``idempotencyKey`` here —
     * otherwise the replay's fingerprint (which folds in the token) would
     * mismatch the original key, or we'd have to drop the token from the
     * fingerprint and dirty OCC. The ``CASE`` rotates only rows that already
     * carry a key; keyless mutation types stay null. Callers pass a fresh UUID.
     */
    @Query(
        """
        UPDATE pending_mutations
        SET status = :toStatus,
            expectedRowVersion = :freshToken,
            idempotencyKey = CASE
                WHEN idempotencyKey IS NOT NULL THEN :rotatedIdempotencyKey
                ELSE idempotencyKey
            END,
            retryCount = 0,
            lastError = NULL
        WHERE id = :id AND status = :fromStatus
        """,
    )
    suspend fun refreshTokenIfStatus(
        id: Long,
        fromStatus: String,
        toStatus: String,
        freshToken: Long,
        rotatedIdempotencyKey: String?,
    ): Int

    /**
     * Atomic ``FAILED → PENDING`` manual retry (no token refresh).
     * Same race-protection rationale as
     * [refreshTokenIfStatus] / [markInFlightIfPending].
     *
     * codex P1 #7: 用户手动 retry 时 ``retryCount = 0``。否则用户点 Retry → 立刻被
     * max_attempts 拦住 → 再点 Retry → 再被拦, 退化成永远困在 FAILED。重置 retryCount
     * 让用户接受风险后能拿到完整的重试预算。
     */
    @Query(
        """
        UPDATE pending_mutations
        SET status = :toStatus,
            retryCount = 0,
            lastError = :lastError
        WHERE id = :id AND status = :fromStatus
        """,
    )
    suspend fun markRetryableIfStatus(
        id: Long,
        fromStatus: String,
        toStatus: String,
        lastError: String,
    ): Int

    /**
     * codex P2 #10 follow-up + PR review: 把 [markInFlightIfPending] 的 retryCount++ 和
     * attemptedAt 一起抵消, 因为 caller(drain engine 的 epoch-abort + cancellation 分支)
     * 在真正 dispatch 前就 abort 了, 这次 tryClaim 不算一次"尝试", 不该计入 max_attempts
     * 配额, 也不该推进 attemptedAt(否则 session 反复 flap 会让两个字段都静默漂移)。
     *
     * **Status guard**: `AND status = :inFlightStatus` 保护——只对刚 tryClaim 成功的
     * IN_FLIGHT row 起效, 防止后续 caller 误调到 PENDING/CONFLICT/FAILED row 上把状态
     * 强翻 PENDING + 抵消 retryCount。
     *
     * **lastError 故意不写**: 保留任何先前 markRetryable 写下的诊断(如 "server 503"),
     * abort 本身只是窗口期事件, 不该淹没真正的根因。drain engine 的 `aborted` 计数器在
     * batch 层提供 abort 信号。
     */
    @Query(
        """
        UPDATE pending_mutations
        SET status = :pendingStatus,
            retryCount = CASE WHEN retryCount > 0 THEN retryCount - 1 ELSE 0 END,
            attemptedAt = NULL
        WHERE id = :id AND status = :inFlightStatus
        """,
    )
    suspend fun revertClaimWithoutAttempt(
        id: Long,
        pendingStatus: String,
        inFlightStatus: String,
    ): Int

    /**
     * Atomic delete-if-status. Caller passes the status they think
     * the row is in (CONFLICT or FAILED depending on which surface
     * is calling); rowcount = 0 means another surface already moved
     * the row out of that state.
     */
    @Query(
        """
        DELETE FROM pending_mutations
        WHERE id = :id AND status = :expectedStatus
        """,
    )
    suspend fun deleteIfStatus(id: Long, expectedStatus: String): Int

    /**
     * Cascade a new ``expected_row_version`` to every still-PENDING
     * row that targets the same row as a just-succeeded mutation.
     *
     * Why: offline chain A → B against the same target. A is
     * enqueued with token T0; client's only known token at the
     * moment is still T0 so B is also enqueued with T0. After A
     * lands, server is at T1. Without this cascade B replays with
     * T0 and fakes a state_conflict against itself.
     *
     * Limited to PENDING rows so a CONFLICT / FAILED row whose
     * user-pick is still pending doesn't get its snapshot silently
     * overwritten.
     */
    @Query(
        """
        UPDATE pending_mutations
        SET expectedRowVersion = :freshToken
        WHERE serverUrl = :serverUrl
          AND ledgerId = :ledgerId
          AND targetId = :targetId
          AND status = :pendingStatus
        """,
    )
    suspend fun cascadeFreshTokenForTarget(
        serverUrl: String,
        ledgerId: String,
        targetId: String,
        pendingStatus: String,
        freshToken: Long,
    ): Int

    // ---------------------------------------------------------------
    // Reads (drain + UI)
    // ---------------------------------------------------------------

    /**
     * Drain worker entry point: oldest PENDING rows whose target
     * has NO unresolved sibling (IN_FLIGHT / CONFLICT / FAILED),
     * capped at [limit].
     *
     * The unresolved-sibling exclusion is in the SQL — not a Kotlin
     * post-filter — so ``LIMIT`` is applied AFTER skipping blocked
     * targets. [codex round-3 P2#1] fix: with a Kotlin post-filter,
     * if the first 25 PENDING rows all target an ``expense:1`` that
     * already has a CONFLICT sibling, the 26th runnable row (for
     * ``expense:2``) never enters the batch and the drain returns
     * IDLE forever even though there's real work available.
     *
     * Same-target dedup (only the oldest PENDING row per target
     * runs in a given pass) is also pushed into SQL so ``LIMIT`` is
     * applied after duplicate targets are removed. Otherwise 25 queued
     * edits for one expense can consume the whole batch and starve
     * other runnable targets until later drain passes.
     */
    @Query(
        """
        SELECT * FROM pending_mutations AS pm
        WHERE pm.serverUrl = :serverUrl
          AND pm.ledgerId = :ledgerId
          AND pm.status = :pendingStatus
          AND NOT EXISTS (
            SELECT 1 FROM pending_mutations AS sib
            WHERE sib.serverUrl = pm.serverUrl
              AND sib.ledgerId = pm.ledgerId
              AND sib.targetId = pm.targetId
              AND sib.status IN (:inFlightStatus, :conflictStatus, :failedStatus)
          )
          AND NOT EXISTS (
            SELECT 1 FROM pending_mutations AS older
            WHERE older.serverUrl = pm.serverUrl
              AND older.ledgerId = pm.ledgerId
              AND older.targetId = pm.targetId
              AND older.status = :pendingStatus
              AND (
                older.createdAt < pm.createdAt
                OR (older.createdAt = pm.createdAt AND older.id < pm.id)
              )
          )
        ORDER BY pm.createdAt ASC, pm.id ASC
        LIMIT :limit
        """,
    )
    suspend fun nextRunnableBatch(
        serverUrl: String,
        ledgerId: String,
        pendingStatus: String,
        inFlightStatus: String,
        conflictStatus: String,
        failedStatus: String,
        limit: Int,
    ): List<PendingMutationEntity>

    /**
     * Plain "PENDING ordered by createdAt" pull. Pre-round-3 entry
     * point — kept for tests and for the recovery sweep code path
     * that doesn't care about target dedup. Drain engine uses
     * [nextRunnableBatch] instead.
     */
    @Query(
        """
        SELECT * FROM pending_mutations
        WHERE serverUrl = :serverUrl
          AND ledgerId = :ledgerId
          AND status = :pendingStatus
        ORDER BY createdAt ASC, id ASC
        LIMIT :limit
        """,
    )
    suspend fun nextPendingBatch(
        serverUrl: String,
        ledgerId: String,
        pendingStatus: String,
        limit: Int,
    ): List<PendingMutationEntity>

    /**
     * True if another row for the same target is currently
     * ``IN_FLIGHT``. PR-2g's drain worker calls this to enforce
     * "same target_id serial" without holding a global drain lock.
     *
     * Note: kept for backward compatibility; PR-2g.1 codex round-2
     * found this is insufficient for serial guarantees (a CONFLICT
     * or FAILED row also blocks same-target progress). Drain uses
     * [hasUnresolvedRowForTarget] instead.
     */
    @Query(
        """
        SELECT COUNT(*) > 0 FROM pending_mutations
        WHERE serverUrl = :serverUrl
          AND ledgerId = :ledgerId
          AND targetId = :targetId
          AND status = :inFlightStatus
        """,
    )
    suspend fun isTargetBusy(
        serverUrl: String,
        ledgerId: String,
        targetId: String,
        inFlightStatus: String,
    ): Boolean

    /**
     * True if any non-terminal row for [targetId] exists — IN_FLIGHT
     * (another drain already running it), CONFLICT (user hasn't
     * picked "keep mine / drop mine" yet), or FAILED (terminal
     * failure waiting for manual retry or dismissal).
     *
     * [codex round-2 finding P1#1] fix: dequeue must NOT advance
     * past an unresolved row for the same target. Otherwise:
     *
     *   A (CONFLICT, user hasn't decided) → B (PENDING)
     *
     * the old logic ran B anyway because only ``IN_FLIGHT`` was
     * checked. B then either fake-conflicts (if A's resolution
     * was DropMine) or applies on top of a state the user hasn't
     * confirmed (if KeepMine).
     */
    @Query(
        """
        SELECT COUNT(*) > 0 FROM pending_mutations
        WHERE serverUrl = :serverUrl
          AND ledgerId = :ledgerId
          AND targetId = :targetId
          AND status IN (:inFlightStatus, :conflictStatus, :failedStatus)
        """,
    )
    suspend fun hasUnresolvedRowForTarget(
        serverUrl: String,
        ledgerId: String,
        targetId: String,
        inFlightStatus: String,
        conflictStatus: String,
        failedStatus: String,
    ): Boolean

    /**
     * Recovery sweep: rows stuck in IN_FLIGHT past [staleCutoffIso]
     * are pushed back to PENDING. Used at drain start to recover
     * from worker cancellations / process death that left a row
     * mid-claim.
     *
     * [codex round-2 finding P1#2] companion: a CancellationException
     * that aborts a drain after the atomic claim succeeded would
     * otherwise pin that row in IN_FLIGHT forever — same-target
     * dedup then permanently blocks all later siblings.
     *
     * **retryCount 故意不抵消**(不同于 [revertClaimWithoutAttempt]): 一个能滞留 IN_FLIGHT
     * 超过 5 分钟的 row 说明 dispatcher 已经被调过, OkHttp 请求可能已经发出去甚至已经被
     * server 处理过——把这次 claim 算成一次真实尝试是正确的。 epoch-abort / cancellation
     * 路径相反, 它们在 dispatch 调用前 / 调用瞬间 abort, 那次 claim 没有真正联网过, 所以
     * 用 revertClaimWithoutAttempt 抵消。
     */
    @Query(
        """
        UPDATE pending_mutations
        SET status = :pendingStatus,
            lastError = :recoveryMessage
        WHERE serverUrl = :serverUrl
          AND ledgerId = :ledgerId
          AND status = :inFlightStatus
          AND (attemptedAt IS NULL OR attemptedAt < :staleCutoffIso)
        """,
    )
    suspend fun recoverStaleInFlight(
        serverUrl: String,
        ledgerId: String,
        pendingStatus: String,
        inFlightStatus: String,
        staleCutoffIso: String,
        recoveryMessage: String,
    ): Int

    /**
     * Returns all non-terminal rows for a given target — useful for
     * the conflict-banner UI when the user opens the affected row's
     * detail page.
     */
    @Query(
        """
        SELECT * FROM pending_mutations
        WHERE serverUrl = :serverUrl
          AND ledgerId = :ledgerId
          AND targetId = :targetId
          AND status IN (:pendingStatus, :inFlightStatus, :conflictStatus, :failedStatus)
        ORDER BY createdAt ASC, id ASC
        """,
    )
    suspend fun activeForTarget(
        serverUrl: String,
        ledgerId: String,
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
        WHERE serverUrl = :serverUrl
          AND ledgerId = :ledgerId
          AND status IN (:pendingStatus, :inFlightStatus)
        """,
    )
    fun observeQueueDepth(
        serverUrl: String,
        ledgerId: String,
        pendingStatus: String,
        inFlightStatus: String,
    ): Flow<Int>

    /**
     * Live stream of rows the user needs to resolve. Drives the
     * conflict-banner UI in PR-2g.
     */
    @Query(
        """
        SELECT * FROM pending_mutations
        WHERE serverUrl = :serverUrl
          AND ledgerId = :ledgerId
          AND status = :conflictStatus
        ORDER BY createdAt ASC, id ASC
        """,
    )
    fun observeConflictRows(
        serverUrl: String,
        ledgerId: String,
        conflictStatus: String,
    ): Flow<List<PendingMutationEntity>>

    /**
     * Live stream of rows that hit a terminal-failure status. Drives
     * the "manual retry / drop" banner the user uses to clear FAILED
     * rows that would otherwise block same-target siblings.
     *
     * [codex round-3 finding P2#2] companion: FAILED rows do block
     * same-target later mutations now (see [nextRunnableBatch]), so
     * there MUST be a UI path to retry or drop them; otherwise a
     * single payload-parse failure deadlocks the rest of the queue
     * for that target.
     */
    @Query(
        """
        SELECT * FROM pending_mutations
        WHERE serverUrl = :serverUrl
          AND ledgerId = :ledgerId
          AND status = :failedStatus
        ORDER BY createdAt ASC, id ASC
        """,
    )
    fun observeFailedRows(
        serverUrl: String,
        ledgerId: String,
        failedStatus: String,
    ): Flow<List<PendingMutationEntity>>

    /**
     * Delete by id. Used when the user picks "drop mine" on a
     * conflict, or when cleanup runs.
     */
    @Query("DELETE FROM pending_mutations WHERE id = :id")
    suspend fun deleteById(id: Long): Int

    /**
     * Prune DONE rows older than [cutoffIso] (ISO-Z). FAILED rows are
     * intentionally excluded: they still need explicit user retry/drop
     * and must not disappear because a retention window elapsed.
     */
    @Query(
        """
        DELETE FROM pending_mutations
        WHERE status = :doneStatus
          AND completedAt IS NOT NULL
          AND completedAt < :cutoffIso
        """,
    )
    suspend fun deleteResolvedBefore(
        doneStatus: String,
        cutoffIso: String,
    ): Int

    /**
     * Drop every row in the outbox. Used only for explicit sign-out
     * or debug/reset paths that intentionally discard local offline
     * edits. Normal ledger/server transitions use binding-scoped
     * rows plus the repository dispatch pause.
     *
     * @return the number of rows removed.
     */
    @Query("DELETE FROM pending_mutations")
    suspend fun clearAll(): Int

    /**
     * One-time v9 → v10 backfill. The 9→10 migration added the
     * ``serverUrl`` / ``ledgerId`` columns with an empty-string default but
     * could not know the active binding (it lives in settings, not the DB),
     * so pre-upgrade rows carry ``('', '')`` and match no binding-scoped
     * query — they would be silently stranded. The app adopts them into the
     * current binding once at drain start (v9 had a single active binding, so
     * the queued rows belong to it). Idempotent: matches nothing once every
     * row carries a real binding.
     *
     * @return the number of legacy rows adopted.
     */
    @Query(
        """
        UPDATE pending_mutations
        SET serverUrl = :serverUrl,
            ledgerId = :ledgerId
        WHERE serverUrl = '' AND ledgerId = ''
        """,
    )
    suspend fun adoptLegacyBinding(serverUrl: String, ledgerId: String): Int
}

package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationDao
import com.ticketbox.data.local.PendingMutationEntity
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.concurrent.atomic.AtomicLong

/**
 * ADR-0038 PR-2g: offline outbox queue.
 *
 * This repository is the queue surface mutation call sites use
 * when going offline. Rows are scoped to the current ``serverUrl``
 * and ``ledgerId`` so cloud/server switches, ledger switches, and
 * device rebinds do not replay old rows under the new binding.
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
 *    targets. The WorkManager drain worker calls this in a loop.
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
    private val bindingProvider: () -> OutboxBinding = { OutboxBinding.DEFAULT },
    /**
     * Reactive binding source for the live UI streams ([observeStatus] and
     * friends). When supplied (AppContainer wires it from the active-ledger
     * settings flow), observe* re-subscribe to the new binding on a ledger
     * switch instead of staying pinned to the binding present when the UI
     * first subscribed. Null (tests / non-Android) falls back to a one-shot
     * snapshot read lazily at collection time — the historical behaviour.
     */
    private val bindingChanges: Flow<OutboxBinding>? = null,
    /**
     * Fired immediately after a row is persisted by [enqueue]. Used
     * by AppContainer to schedule a one-time [OutboxDrainWorker]
     * tick — same pattern as the [OutboxDrainWorker]'s ``logWarning``
     * injection (PR-2g.2): the side effect that needs Android
     * primitives (WorkManager / Context) stays out of the
     * repository, the repository stays a pure persistence layer.
     *
     * Defaulted to no-op so existing tests and any non-Android
     * caller can construct ``OutboxRepository`` without wiring the
     * scheduler.
     */
    private val onEnqueued: () -> Unit = {},
    /**
     * Fired immediately after [clearAll] drains the DAO. AppContainer
     * wires this to [OutboxScheduler.cancel] FOLLOWED by
     * [OutboxScheduler.ensurePeriodic] so an in-flight worker
     * doesn't try to drain a now-empty queue under the new session
     * AND the periodic heartbeat is re-armed for whatever queue the
     * next session populates (codex round-9 P2 fix — without the
     * re-arm, cold restart was the only path back to a periodic
     * tick).
     *
     * Same best-effort semantics as [onEnqueued] (we catch
     * [Exception] internally; JVM-level Errors propagate).
     */
    private val onClearAll: () -> Unit = {},
) {
    private fun currentBinding(): OutboxBinding = bindingProvider().normalized()

    /**
     * ADR-0038 PR-2g.3 round-9 P1: session-boundary epoch.
     *
     * Incremented at the start of [clearAll]. A drain pass captures
     * this value before dequeue and re-checks it after [tryClaim]
     * but before dispatch. If the epoch changed, the drain knows a
     * session boundary fired mid-pass. The drain must not dispatch
     * a row loaded under the old binding after credentials changed,
     * so it skips the rest of the batch and exits.
     *
     * Room rows also carry ``serverUrl`` / ``ledgerId`` and all DAO
     * drain reads are binding-scoped. The epoch is still needed for
     * the narrower in-process case where a worker has already loaded
     * a row and is about to dispatch while credentials are changing.
     */
    private val sessionEpoch = AtomicLong(0L)

    /**
     * Snapshot of the session-boundary epoch — used by
     * [OutboxDrainEngine.drainOnce] to detect whether a [clearAll]
     * fired between dequeue and dispatch.
     */
    fun currentSessionEpoch(): Long = sessionEpoch.get()

    /**
     * Test-only hook: bump the epoch counter without wiping the
     * DAO. Production code uses [clearAll] which does both
     * atomically; this lets the OutboxDrainEngine post-claim guard
     * be exercised in a unit test without the dao.clearAll() also
     * deleting the row the test wants to keep claimed.
     */
    internal fun bumpSessionEpochForTesting() {
        sessionEpoch.incrementAndGet()
    }

    /**
     * ADR-0038 PR-2g.3 codex round-10 follow-up: dispatch lease.
     *
     * Closes the residual race after round-9's epoch guard:
     *   1. drain captures epoch = N
     *   2. drain tryClaim succeeds + post-claim epoch check passes
     *      (still N)
     *   3. coroutine suspends (scheduler yields)
     *   4. a binding transition starts (epoch bumps to N+1)
     *   5. session coordinator writes new serverUrl + sessionToken
     *   6. drain resumes, calls dispatcher.dispatch(row)
     *   7. dispatch resolves apiProvider() lazily; OkHttp
     *      interceptor lazily reads the (NEW) sessionToken
     *   8. request goes out under NEW session for OLD row →
     *      wrong-session replay
     *
     * The epoch guard alone can't close this because the credential
     * read inside dispatch happens AFTER the check. The fix is a
     * [Mutex] held by:
     *   - [OutboxDrainEngine.drainOnce] across BOTH the epoch check
     *     AND the entire ``dispatcher.dispatch(row)`` (so the
     *     OkHttp token-read inside dispatch can't be interleaved
     *     with a binding transition).
     *   - [withBindingTransition] across the epoch bump and all
     *     credential/cache writes.
     *
     * Because [LocalLedgerSessionCoordinator] and
     * [ExpenseRepositoryCore.clearBinding] mutate credentials inside
     * [withBindingTransition], credential mutations always happen
     * AFTER any in-flight dispatch completes. Worst case is
     * "old-session in-flight at boundary moment" — the in-flight
     * request finishes under the old session, then the session
     * changes.
     *
     * Cost: a session transition may block up to one outbox call
     * timeout. We trade latency for correctness.
     */
    private val dispatchLease = Mutex()
    private val bindingTransitionLease = Mutex()

    /**
     * Run [block] while holding the dispatch lease. Used by
     * [OutboxDrainEngine.drainOnce] to serialise dispatch against
     * [clearAll]. See [dispatchLease] KDoc for the race this closes.
     */
    suspend fun <T> withDispatchLease(block: suspend () -> T): T =
        dispatchLease.withLock { block() }

    /**
     * Hold the complete credential/binding mutation boundary.
     *
     * [enqueue] snapshots ``serverUrl`` + ``ledgerId`` from local
     * settings. During a server or ledger switch those two values
     * are written in separate stores, so an enqueue that interleaves
     * with the transition could otherwise persist a mixed binding.
     * This method blocks both dispatch and enqueue while the caller
     * mutates credentials, bumps the epoch before any new credential
     * is visible, and optionally clears the queue for explicit
     * sign-out or debug rebinding.
     */
    suspend fun <T> withBindingTransition(
        clearExistingRows: Boolean = false,
        block: suspend () -> T,
    ): T {
        var notifyBoundary = false
        try {
            return dispatchLease.withLock {
                bindingTransitionLease.withLock {
                    sessionEpoch.incrementAndGet()
                    notifyBoundary = true
                    if (clearExistingRows) {
                        dao.clearAll()
                    }
                    block()
                }
            }
        } finally {
            if (notifyBoundary) {
                notifyClearBoundary()
            }
        }
    }

    /**
     * Persist a mutation snapshot for later replay.
     *
     * [onEnqueued] fires after the row is committed so the caller's
     * scheduler (WorkManager in production) can fire a one-time
     * drain ASAP — the user doesn't wait up to 15 min for the
     * periodic tick. The drain itself respects same-target serial
     * (see [dequeueNextRunnable]) so a burst of enqueues collapses
     * into one drain pass via the [OutboxScheduler]'s ``KEEP``
     * policy.
     *
     * Note the callback is wrapped in a try/catch (Exception): it's
     * a best-effort "wake the worker now" signal, not a precondition
     * for the row being usable. If [OutboxScheduler.enqueueOnce]
     * throws (WorkManager not initialised in a test / IPC failure /
     * etc.) the row is still committed and the periodic worker will
     * pick it up. Letting that exception escape would make a
     * persisted mutation look like a failed insert to the caller.
     *
     * We catch [Exception], **not** [Throwable] — [codex round-8 P2]
     * fix. The original ``runCatching`` formulation caught Throwable
     * by definition (Kotlin's runCatching), which conflicts with
     * the round-5 rule we enforce in [OutboxDrainEngine] (catch
     * Exception, not Throwable, so OOM / LinkageError /
     * StackOverflow propagate up to the OS-level worker restart).
     *
     * @return the row id of the freshly inserted outbox entry.
     */
    suspend fun enqueue(
        type: PendingMutationType,
        targetId: String,
        payloadJson: String,
        expectedUpdatedAt: String,
    ): Long {
        val id = bindingTransitionLease.withLock {
            val binding = currentBinding()
            val row = PendingMutationEntity(
                serverUrl = binding.serverUrl,
                ledgerId = binding.ledgerId,
                type = type.wireValue,
                targetId = targetId,
                payload = payloadJson,
                expectedUpdatedAt = expectedUpdatedAt,
                status = PendingMutationStatus.Pending.wireValue,
                createdAt = nowIso(),
            )
            dao.insert(row)
        }
        try {
            onEnqueued()
        } catch (_: Exception) {
            // Best-effort scheduler kick; the row is already in the
            // DAO and the periodic worker (15-min tick) will drain
            // it. JVM-level Errors (OOM / StackOverflow / Linkage)
            // propagate up by design.
        }
        return id
    }

    suspend fun pauseForBindingTransition() {
        withBindingTransition(clearExistingRows = false) {}
    }

    /**
     * Drop every queued mutation. Used for explicit sign-out or
     * internal debug rebind paths where preserving offline edits
     * would keep private data after credentials are intentionally
     * removed. Ledger/server switches use [pauseForBindingTransition]
     * instead; durable binding columns keep old rows from replaying
     * under the wrong session.
     *
     * @return the number of rows dropped.
     */
    suspend fun clearAll(): Int {
        var removed = 0
        withBindingTransition(clearExistingRows = false) {
            removed = dao.clearAll()
        }
        return removed
    }

    private fun notifyClearBoundary() {
        try {
            onClearAll()
        } catch (_: Exception) {
            // Best-effort scheduler cancel/re-arm signal. JVM-level
            // Errors still propagate; see [enqueue] for the same
            // Exception-not-Throwable rationale.
        }
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
     *    ``markInFlightIfPending`` is per-row atomic. The DAO now
     *    also applies this same-target filter before ``LIMIT`` so
     *    duplicate targets do not consume the whole batch.
     * 3. Returns the public [OutboxRow] view (not the raw Entity)
     *    so the drain engine doesn't depend on Room types.
     */
    suspend fun dequeueNextRunnable(limit: Int = DEFAULT_DRAIN_BATCH): List<OutboxRow> {
        val binding = currentBinding()
        // [codex round-3 P2#1 / round-4 P1] Use the SQL-side filter
        // so LIMIT applies AFTER unresolved targets are excluded.
        // Round-3 introduced ``nextRunnableBatch`` but a rebase wiped
        // out the production caller; round-4 wires it back.
        val candidates = dao.nextRunnableBatch(
            serverUrl = binding.serverUrl,
            ledgerId = binding.ledgerId,
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
     * One-time v9 → v10 adoption. The 9 → 10 migration added the
     * ``serverUrl`` / ``ledgerId`` columns with an empty-string default but
     * couldn't know the active binding (it lives in settings, not the DB), so
     * pre-upgrade rows carry ``('', '')`` and match no binding-scoped query.
     * v9 tracked no binding but had a single active one, so those stranded
     * rows belong to whatever the app is bound to now. The drain engine calls
     * this at the start of every pass; it's a no-op once adopted (or while
     * unbound), so no extra startup wiring is needed.
     *
     * @return the number of legacy rows adopted into the current binding.
     */
    suspend fun adoptLegacyRowsForCurrentBinding(): Int {
        val binding = currentBinding()
        if (binding.serverUrl.isEmpty() || binding.ledgerId.isEmpty()) return 0
        return bindingTransitionLease.withLock {
            dao.adoptLegacyBinding(serverUrl = binding.serverUrl, ledgerId = binding.ledgerId)
        }
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
        return currentBinding().let { binding ->
            dao.recoverStaleInFlight(
                serverUrl = binding.serverUrl,
                ledgerId = binding.ledgerId,
                pendingStatus = PendingMutationStatus.Pending.wireValue,
                inFlightStatus = PendingMutationStatus.InFlight.wireValue,
                staleCutoffIso = ISO.format(cutoff),
                recoveryMessage = "recovered_from_stuck_in_flight",
            )
        }
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
        currentBinding().let { binding ->
            dao.cascadeFreshTokenForTarget(
                serverUrl = binding.serverUrl,
                ledgerId = binding.ledgerId,
                targetId = targetId,
                pendingStatus = PendingMutationStatus.Pending.wireValue,
                freshToken = newToken,
            )
        }

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
     * Binding source the live UI streams follow. A reactive [bindingChanges]
     * (AppContainer wires it from the active-ledger settings flow) lets the
     * observe* streams re-target the new binding on a ledger switch via
     * [flatMapLatest]; null falls back to a single snapshot read lazily at
     * collection time so tests / non-Android callers keep the old behaviour.
     */
    private fun bindingFlow(): Flow<OutboxBinding> =
        (bindingChanges ?: flow { emit(currentBinding()) })
            .map { it.normalized() }
            .distinctUntilChanged()

    /**
     * Live queue-depth surface for the global "你有 N 笔待同步"
     * status pill. Re-subscribes to the new binding when the active ledger
     * changes (see [bindingFlow]).
     */
    @OptIn(ExperimentalCoroutinesApi::class)
    fun observeQueueDepth(): Flow<Int> =
        bindingFlow().flatMapLatest { binding ->
            dao.observeQueueDepth(
                serverUrl = binding.serverUrl,
                ledgerId = binding.ledgerId,
                pendingStatus = PendingMutationStatus.Pending.wireValue,
                inFlightStatus = PendingMutationStatus.InFlight.wireValue,
            )
        }

    /**
     * Live stream of rows in CONFLICT state. The conflict-banner
     * UI in PR-2g subscribes to this and renders one banner per
     * row with "keep mine / drop mine" buttons.
     *
     * Status string is converted back to the enum on read so the
     * UI layer doesn't have to know wire values.
     */
    @OptIn(ExperimentalCoroutinesApi::class)
    fun observeConflicts(): Flow<List<OutboxRow>> =
        bindingFlow().flatMapLatest { binding ->
            dao.observeConflictRows(
                serverUrl = binding.serverUrl,
                ledgerId = binding.ledgerId,
                conflictStatus = PendingMutationStatus.Conflict.wireValue,
            )
        }
            .map { rows -> rows.map { it.toDomain() } }

    /**
     * Live stream of FAILED rows for the "manual retry / drop"
     * banner. Counterpart of [observeConflicts]; both states block
     * same-target later mutations and need a UI surface to clear.
     */
    @OptIn(ExperimentalCoroutinesApi::class)
    fun observeFailed(): Flow<List<OutboxRow>> =
        bindingFlow().flatMapLatest { binding ->
            dao.observeFailedRows(
                serverUrl = binding.serverUrl,
                ledgerId = binding.ledgerId,
                failedStatus = PendingMutationStatus.Failed.wireValue,
            )
        }
            .map { rows -> rows.map { it.toDomain() } }

    fun observeStatus(): Flow<OutboxStatus> =
        combine(observeQueueDepth(), observeConflicts(), observeFailed()) { queueDepth, conflicts, failed ->
            OutboxStatus(
                queueDepth = queueDepth,
                conflicts = conflicts,
                failed = failed,
            )
        }

    suspend fun activeForTarget(targetId: String): List<OutboxRow> =
        currentBinding().let { binding ->
            dao.activeForTarget(
                serverUrl = binding.serverUrl,
                ledgerId = binding.ledgerId,
                targetId = targetId,
                pendingStatus = PendingMutationStatus.Pending.wireValue,
                inFlightStatus = PendingMutationStatus.InFlight.wireValue,
                conflictStatus = PendingMutationStatus.Conflict.wireValue,
                failedStatus = PendingMutationStatus.Failed.wireValue,
            )
        }.map { it.toDomain() }

    /**
     * Garbage-collect completed DONE rows older than [retentionMillis].
     *
     * FAILED rows are unresolved user-action rows, not retention
     * artifacts. They stay until the user retries or drops them; this
     * keeps a future DAO refactor from silently deleting failed local
     * mutations after seven days.
     */
    suspend fun gcCompleted(retentionMillis: Long = DEFAULT_RETENTION_MS): Int {
        val cutoff = Instant.now(clock).minusMillis(retentionMillis)
        return dao.deleteResolvedBefore(
            doneStatus = PendingMutationStatus.Done.wireValue,
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
    val serverUrl: String,
    val ledgerId: String,
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

data class OutboxBinding(
    val serverUrl: String,
    val ledgerId: String,
) {
    fun normalized(): OutboxBinding =
        OutboxBinding(
            serverUrl = serverUrl.trim().trimEnd('/'),
            ledgerId = ledgerId.trim(),
        )

    companion object {
        val DEFAULT = OutboxBinding(serverUrl = "", ledgerId = "")
    }
}

data class OutboxStatus(
    val queueDepth: Int,
    val conflicts: List<OutboxRow>,
    val failed: List<OutboxRow>,
) {
    val needsUserAction: Boolean
        get() = conflicts.isNotEmpty() || failed.isNotEmpty()
}

private fun PendingMutationEntity.toDomain(): OutboxRow = OutboxRow(
    id = id,
    serverUrl = serverUrl,
    ledgerId = ledgerId,
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

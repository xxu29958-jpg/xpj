package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationDao
import com.ticketbox.data.local.PendingMutationEntity
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.UUID
import java.util.concurrent.atomic.AtomicLong

internal data class PendingMutationIntent(
    val type: PendingMutationType,
    val targetId: String,
    val payloadJson: String,
    val expectedRowVersion: Long,
    val idempotencyKey: String? = null,
) {
    /** Single and batch acceptance encode the same immutable command under the verified binding. */
    fun toEntity(binding: OutboxBinding, createdAt: String): PendingMutationEntity = PendingMutationEntity(
        serverUrl = binding.serverUrl,
        ledgerId = binding.ledgerId,
        ownerKey = requireNotNull(binding.owner).storageKey,
        type = type.wireValue,
        targetId = targetId,
        payload = payloadJson,
        expectedRowVersion = expectedRowVersion,
        idempotencyKey = idempotencyKey,
        status = PendingMutationStatus.Pending.wireValue,
        createdAt = createdAt,
    )
}

/**
 * ADR-0038 PR-2g: offline outbox queue.
 *
 * This repository is the queue surface mutation call sites use
 * when going offline. Rows are scoped to the current ``serverUrl``
 * and ``ledgerId`` so cloud/server switches, ledger switches, and
 * device rebinds do not replay old rows under the new binding.
 *
 * Concurrency contract enforced here:
 * 1. [enqueue] publishes the original bound intent. Each mutation owner
 *    decides its local presentation; a queued correction is never a fact.
 *    Room acceptance precedes the scheduler notification.
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
private data class OutboxBindingSource(
    val current: () -> OutboxBinding,
    val changes: Flow<OutboxBinding>?,
)

private data class OutboxLifecycleHooks(
    val onEnqueued: () -> Unit,
    val onClearAll: () -> Unit,
    val onRowsDeleted: suspend () -> Unit,
)

class OutboxRepository private constructor(
    private val dao: PendingMutationDao,
    private val clock: Clock,
    bindingSource: OutboxBindingSource,
    lifecycleHooks: OutboxLifecycleHooks,
    private val writeBlock: Flow<OutboxWriteBlock?>,
) {
    private val bindingProvider = bindingSource.current
    /**
     * Reactive binding source for the live UI streams ([observeStatus] and
     * friends). When supplied (AppContainer wires it from the active-ledger
     * settings flow), observe* re-subscribe to the new binding on a ledger
     * switch. [bindingRevision] also re-reads [bindingProvider] after a
     * same-ledger server transition, so status flows cannot stay pinned to
     * the previous origin. Null keeps the same revision-driven behaviour for
     * tests and non-Android callers.
     */
    private val bindingChanges = bindingSource.changes
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
    private val onEnqueued = lifecycleHooks.onEnqueued
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
    private val onClearAll = lifecycleHooks.onClearAll
    private val onRowsDeleted = lifecycleHooks.onRowsDeleted

    private val mutableAcceptedReplayRevision = MutableStateFlow(0L)
    val acceptedReplayRevision: StateFlow<Long> = mutableAcceptedReplayRevision.asStateFlow()
    internal fun noteAcceptedReplay() = mutableAcceptedReplayRevision.update { it + 1L }

    // Composition boundary: the compatibility flow is a real status dependency,
    // alongside persistence, binding and scheduling. Keep these inputs explicit.
    @Suppress("LongParameterList")
    constructor(
        dao: PendingMutationDao,
        clock: Clock = Clock.systemUTC(),
        bindingProvider: () -> OutboxBinding,
        bindingChanges: Flow<OutboxBinding>? = null,
        onEnqueued: () -> Unit = {},
        onClearAll: () -> Unit = {},
        writeBlock: Flow<OutboxWriteBlock?> = flowOf(null),
        onRowsDeleted: suspend () -> Unit,
    ) : this(
        dao = dao,
        clock = clock,
        bindingSource = OutboxBindingSource(bindingProvider, bindingChanges),
        lifecycleHooks = OutboxLifecycleHooks(onEnqueued, onClearAll, onRowsDeleted),
        writeBlock = writeBlock,
    )

    /**
     * ADR-0038 PR-2g.3 round-9 P1: session-boundary epoch.
     *
     * Incremented at the start of every [withBindingTransition]. A drain pass captures
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
     * [OutboxDrainEngine.drainOnce] to detect whether a binding transition
     * fired between dequeue and dispatch.
     */
    fun currentSessionEpoch(): Long = sessionEpoch.get()

    /**
     * Test-only hook: bump the epoch counter without wiping the
     * DAO. Production code uses [withBindingTransition], which also
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
     *   7. dispatch could otherwise acquire a bound service for the
     *      NEW session after the row was selected
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
    private val bindingRevision = MutableStateFlow(0L)

    private suspend fun currentBinding(): OutboxBinding =
        bindingTransitionLease.withLock {
            canonicalBindingWithAliasesMigratedLocked(bindingProvider())
        }

    private suspend fun canonicalBindingWithAliasesMigratedLocked(
        binding: OutboxBinding,
    ): OutboxBinding {
        val raw = binding.trimmed()
        val canonical = raw.normalized()
        if (
            raw.serverUrl != canonical.serverUrl &&
            raw.ledgerId.isNotEmpty() &&
            raw.owner != null &&
            canonical.serverUrl.isNotEmpty()
        ) {
            dao.migrateServerUrlAlias(
                ownerKey = requireNotNull(raw.owner).storageKey,
                oldServerUrl = raw.serverUrl,
                newServerUrl = canonical.serverUrl,
                ledgerId = raw.ledgerId,
            )
        }
        return canonical
    }

    /**
     * Run [block] while holding the dispatch lease. Used by
     * [OutboxDrainEngine.drainOnce] to serialise dispatch against
     * binding transitions. See [dispatchLease] KDoc for the race this closes.
     */
    suspend fun <T> withDispatchLease(block: suspend () -> T): T =
        dispatchLease.withLock { block() }

    /**
     * Commit binding-scoped local state at the same linearization boundary as
     * session transitions. The complete origin/ledger/token snapshot is checked
     * only after the lease is held, so an old response cannot repopulate Room
     * after a same-ledger rebind cleared it.
     */
    internal suspend fun <T> withActiveBinding(
        boundRequest: BoundLedgerRequest,
        block: suspend (OutboxBinding) -> T,
    ): T = bindingTransitionLease.withLock {
        val binding = canonicalBindingWithAliasesMigratedLocked(bindingProvider())
        boundRequest.requireStillActiveFor(binding)
        block(binding)
    }

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
        serverAliasMigration: OutboxServerAliasMigration? = null,
        block: suspend () -> T,
    ): T {
        var notifyBoundary = false
        var removed = 0
        try {
            return dispatchLease.withLock {
                bindingTransitionLease.withLock {
                    sessionEpoch.incrementAndGet()
                    notifyBoundary = true
                    try {
                        if (clearExistingRows) {
                            removed = dao.clearAll()
                        }
                        serverAliasMigration?.let { migration ->
                            bindingProvider().owner?.storageKey?.let { ownerKey ->
                                dao.migrateServerUrlAlias(
                                    ownerKey = ownerKey,
                                    oldServerUrl = migration.oldServerUrl,
                                    newServerUrl = migration.newServerUrl,
                                    ledgerId = migration.ledgerId,
                                )
                            }
                        }
                        block()
                    } finally {
                        bindingRevision.update { revision -> revision + 1 }
                    }
                }
            }
        } finally {
            if (notifyBoundary) {
                notifyClearBoundary()
            }
            notifyRowsDeleted(removed)
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
     * into the existing serial drain chain via [OutboxScheduler].
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
        expectedRowVersion: Long,
        // ADR-0042 request idempotency key. Defaulted null so Slice A (column +
        // plumbing) lands without touching call sites; Slice B+ passes the
        // intent-time UUID so committed-but-unseen replays dedupe server-side.
        idempotencyKey: String? = null,
    ): Long = enqueue(
        boundRequest = null,
        intent = PendingMutationIntent(
            type = type,
            targetId = targetId,
            payloadJson = payloadJson,
            expectedRowVersion = expectedRowVersion,
            idempotencyKey = idempotencyKey,
        ),
    )

    /**
     * Persist a fallback intent only if the request's complete origin/ledger/
     * credential snapshot is still current at the outbox linearization point.
     */
    internal suspend fun enqueue(
        boundRequest: BoundLedgerRequest?,
        intent: PendingMutationIntent,
        validateTargetRows: ((List<OutboxRow>) -> Unit)? = null,
        afterPersisted: suspend () -> Unit = {},
    ): Long {
        val id = bindingTransitionLease.withLock {
            val binding = canonicalBindingWithAliasesMigratedLocked(bindingProvider())
            boundRequest?.requireStillActiveFor(binding)
            binding.requireReadyForEnqueue()
            validateTargetRows?.invoke(activeForTarget(binding, intent.targetId,
                ACTIVE_STATUS_VALUES + PendingMutationStatus.Done.wireValue))
            val row = intent.toEntity(binding, nowIso())
            dao.insertAndPublish(row, afterPersisted)
        }
        schedulePending()
        return id
    }

    /** Reuses the existing scheduler after a durable insertion or explicit original retry. */
    internal fun schedulePending() {
        try {
            onEnqueued()
        } catch (_: Exception) {
            // The durable row remains; the existing periodic worker will drain it.
        }
    }

    /** Files must already be durable, with the upload file lock held across this bound transaction. */
    internal suspend fun enqueueUploadBatch(
        boundRequest: BoundLedgerRequest,
        intents: List<PendingMutationIntent>,
    ): List<Long> {
        require(intents.size in 1..100)
        require(intents.all { it.type == PendingMutationType.UploadScreenshot && it.expectedRowVersion == 0L })
        val keys = intents.map { requireNotNull(it.idempotencyKey) }
        require(keys.distinct().size == keys.size && keys.all(::isUploadIntentFileKey))
        val ids = withActiveBinding(boundRequest) { binding ->
            binding.requireReadyForEnqueue()
            val existing = dao.findByIdempotencyKeys(binding.ownerStorageKey, binding.ledgerId,
                PendingMutationType.UploadScreenshot.wireValue, keys)
            if (existing.isNotEmpty()) {
                check(existing.size == intents.size) { "Incomplete original upload acceptance" }
                val byKey = existing.associateBy { it.idempotencyKey }
                intents.map { intent ->
                    val row = checkNotNull(byKey[intent.idempotencyKey])
                    check(row.payload == intent.payloadJson && row.targetId == intent.targetId &&
                        row.expectedRowVersion == intent.expectedRowVersion) { "Original upload intent changed" }
                    row.id
                }
            } else {
                val createdAt = nowIso()
                dao.insertBatch(intents.map { it.toEntity(binding, createdAt) })
            }
        }
        schedulePending()
        return ids
    }

    /** Includes delivered and expired originals, so an uncertain acceptance cannot allocate another command. */
    internal suspend fun originalUploadRows(boundRequest: BoundLedgerRequest, keys: List<String>): List<OutboxRow> =
        withActiveBinding(boundRequest) { binding ->
            dao.findByIdempotencyKeys(binding.ownerStorageKey, binding.ledgerId,
                PendingMutationType.UploadScreenshot.wireValue, keys).map { it.toDomain() }
        }

    /** Raw types stay visible: an unknown future kind makes file ownership unprovable. */
    internal suspend fun allRowsForUploadFileReferences(): List<PendingMutationEntity> = dao.allRows()

    /** Stop and Retry share the original send/binding boundary; neither can replace an original key. */
    internal suspend fun recoverUploadGroup(
        boundRequest: BoundLedgerRequest,
        targetId: String,
        drop: Boolean,
        retryIds: List<Long> = emptyList(),
    ): Boolean {
        var retried = 0
        var removed = 0
        val changed = dispatchLease.withLock {
            withActiveBinding(boundRequest) { binding ->
                if (drop) {
                    removed = dao.deleteUnfinishedUploadGroup(binding.ownerStorageKey, binding.ledgerId, targetId)
                    removed > 0
                } else {
                    val eligible = activeForTarget(binding, targetId).filter { row ->
                        row.type == PendingMutationType.UploadScreenshot &&
                            row.status == PendingMutationStatus.Failed && row.id in retryIds
                    }
                    var expired = false
                    for (row in eligible) {
                        if (expireOverAgeOnResolve(row.id, binding, PendingMutationStatus.Failed.wireValue)) {
                            expired = true
                        } else {
                            retried += dao.retryFailed(row.id, binding.ownerStorageKey, binding.ledgerId, NON_RETRYABLE_UPLOAD_ERRORS)
                        }
                    }
                    expired || retried > 0
                }
            }
        }
        if (retried > 0) schedulePending()
        notifyRowsDeleted(removed)
        return changed
    }

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
    suspend fun clearAll(): Int {
        val removed = withBindingTransition(clearExistingRows = false) { dao.clearAll() }
        notifyRowsDeleted(removed)
        return removed
    }

    /** Remove only legacy or foreign-owner rows after explicit user confirmation. */
    suspend fun clearQuarantined(): Int {
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
    private suspend fun notifyRowsDeleted(removed: Int) {
        if (removed <= 0) return
        try {
            onRowsDeleted()
        } catch (error: CancellationException) {
            throw error
        } catch (_: Exception) {
            // Keep unclaimed files for the next complete reference check; never infer another row deletion.
        }
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
    suspend fun dequeueNextRunnable(limit: Int = DEFAULT_DRAIN_BATCH, excludedIds: List<Long> = emptyList()): List<OutboxRow> {
        val binding = currentBinding()
        // [codex round-3 P2#1 / round-4 P1] Use the SQL-side filter
        // so LIMIT applies AFTER unresolved targets are excluded.
        // Round-3 introduced ``nextRunnableBatch`` but a rebase wiped
        // out the production caller; round-4 wires it back.
        val candidates = dao.nextRunnableBatch(
            ownerKey = binding.ownerStorageKey,
            ledgerId = binding.ledgerId,
            unresolvedStatuses = UNRESOLVED_STATUS_VALUES,
            limit = limit,
            excludedIds = excludedIds,
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
        return currentBinding().let { binding ->
            dao.recoverStaleInFlight(
                ownerKey = binding.ownerStorageKey,
                ledgerId = binding.ledgerId,
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

    internal suspend fun discardOriginalExpense(boundRequest: BoundLedgerRequest, row: OutboxRow,
        afterDeleted: suspend () -> Unit = {}): Boolean = withActiveBinding(boundRequest) { binding ->
        check(row.type in setOf(PendingMutationType.CreateExpense, PendingMutationType.CorrectExpense) && row.status in setOf(
            PendingMutationStatus.Failed, PendingMutationStatus.Conflict, PendingMutationStatus.Done, PendingMutationStatus.Pending,
        ))
        check(row.type != PendingMutationType.CreateExpense || row.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict))
        check(row.ownerKey == binding.ownerStorageKey && row.ledgerId == binding.ledgerId)
        dao.deleteAndPublish(row.id, binding.ownerStorageKey, binding.ledgerId, row.status.wireValue, afterDeleted)
    }.also { changed -> if (changed) { schedulePending(); if (row.type == PendingMutationType.CreateExpense) notifyRowsDeleted(1) } }

    suspend fun markDone(id: Long, cacheRefreshVersion: Long? = null, receiptJson: String? = null) {
        dao.markDone(
            id = id,
            status = PendingMutationStatus.Done.wireValue,
            completedAt = nowIso(),
            lastError = cacheRefreshVersion?.let { "$CORRECTION_REFRESH_PREFIX$it" },
            receiptJson = receiptJson,
        )
    }

    /** Acknowledges adopted roots without changing delivery, original OCC or command bytes. */
    internal suspend fun acknowledgeCorrectionRefresh(boundRequest: BoundLedgerRequest, versions: Map<Long, Long>) =
        bindingTransitionLease.withLock {
            val binding = canonicalBindingWithAliasesMigratedLocked(bindingProvider())
            try {
                boundRequest.requireStillActiveFor(binding)
            } catch (_: RepositoryException) {
                // Adoption already completed. A later transition leaves its marker for the next bound read.
                return@withLock
            }
            val rows = dao.observeActiveByTypes(binding.ownerStorageKey, binding.ledgerId,
                listOf(PendingMutationType.CorrectExpense.wireValue), listOf(PendingMutationStatus.Done.wireValue)).first()
            for (row in rows) {
                val required = correctionRefreshVersion(row.lastError) ?: continue
                val target = parseExpenseTargetRef(row.targetId)?.toLongOrNull() ?: continue
                if ((versions[target] ?: continue) >= required) {
                    dao.clearCorrectionRefresh(row.id, requireNotNull(row.lastError))
                }
            }
        }

    /**
     * Cascade a freshly-server-returned token to every PENDING row
     * targeting the same row. See
     * [PendingMutationDao.cascadeFreshTokenForTarget] for the why.
     *
     * Returns the count of cascaded rows for tests / telemetry.
     */
    suspend fun cascadeFreshToken(targetId: String, newToken: Long): Int =
        currentBinding().let { binding ->
            dao.cascadeFreshTokenForTarget(
                ownerKey = binding.ownerStorageKey,
                ledgerId = binding.ledgerId,
                targetId = targetId,
                preservedTokenTypes = listOf(PendingMutationType.VoidExpenseOffset.wireValue,
                    PendingMutationType.CreateBillSplitInvitation.wireValue,
                    PendingMutationType.CorrectExpense.wireValue, PendingMutationType.CreateExpenseOffset.wireValue, PendingMutationType.UploadScreenshot.wireValue),
                freshToken = newToken,
            )
        }

    /**
     * Transient failure: keep the row in PENDING so the next drain
     * pass picks it up. ``retryCount`` was already bumped by
     * [tryClaim]; back-off is scheduler-side, but **give-up is engine-side**:
     * [OutboxDrainEngine] checks ``row.retryCount + 1 >= maxAttempts`` in the
     * RetryableFailure branch and routes to [markFailed] instead of
     * [markRetryable] once the cap trips (codex P1 #7).
     */
    suspend fun markRetryable(id: Long, error: String) {
        dao.markRetryable(
            id = id,
            pendingStatus = PendingMutationStatus.Pending.wireValue,
            lastError = error,
        )
    }

    /**
     * codex P2 #10 follow-up: revert a [tryClaim] that aborted before any actual
     * dispatch ran. Undoes the retryCount bump + attemptedAt set so an epoch-abort
     * or mid-dispatch cancellation 不算一次"尝试", 避免 session 反复 flap N 次后
     * max_attempts 假性触发。
     *
     * `internal` 因为只该 engine 用; DAO 也带 `AND status = :inFlightStatus` 守卫,
     * 即使被外部误调也只对 IN_FLIGHT row 起效。
     */
    internal suspend fun revertClaimWithoutAttempt(id: Long) {
        dao.revertClaimWithoutAttempt(
            id = id,
            pendingStatus = PendingMutationStatus.Pending.wireValue,
            inFlightStatus = PendingMutationStatus.InFlight.wireValue,
        )
    }

    suspend fun markConflict(id: Long, serverMessage: String) {
        dao.markConflict(
            id = id,
            status = PendingMutationStatus.Conflict.wireValue,
            lastError = serverMessage,
        )
    }

    /**
     * Move a row to terminal FAILED. ``retryCount`` is **NOT** reset here — the
     * historical attempt count survives so observability / debug surfaces can
     * read it (codex P1 #7). Once the user picks
     * [FailedResolution.Retry][FailedResolution.Retry], the DAO atomic update
     * (`retryFailed` / `requeueFailedWithFreshToken`) zeros it so they get a
     * fresh budget. While the row is FAILED, ``retryCount`` should be treated
     * as historical-only — no future drain decision keys off it.
     */
    suspend fun markFailed(id: Long, error: String, blocksFollowing: Boolean = true) {
        dao.markFailed(
            id = id,
            status = PendingMutationStatus.Failed.wireValue,
            lastError = error,
            blocksFollowing = blocksFollowing,
        )
    }

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
    internal suspend fun resolveConflict(id: Long, resolution: ConflictResolution, boundRequest: BoundLedgerRequest? = null): Boolean =
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
    internal suspend fun resolveFailed(id: Long, resolution: FailedResolution, boundRequest: BoundLedgerRequest? = null): Boolean =
        resolveStatus(id, PendingMutationStatus.Failed, resolution == FailedResolution.Drop,
            (resolution as? FailedResolution.Retry)?.freshToken, boundRequest)

    /** A command owner has reviewed this unverified completed original; remove only its local record. */
    internal suspend fun discardCompletedOriginalSubmission(boundRequest: BoundLedgerRequest, row: OutboxRow): Boolean {
        require(row.type in setOf(PendingMutationType.CreateIncomePlan, PendingMutationType.UpdateIncomePlan,
            PendingMutationType.SaveManualExchangeRate))
        require(row.status == PendingMutationStatus.Done)
        boundRequest.requireStillActiveFor(requireNotNull(row.bindingOrNull()))
        return resolveStatus(row.id, PendingMutationStatus.Done, true, null, boundRequest)
    }

    /** One status-checked recovery owner; only an actual replay or deletion wakes successors. */
    private suspend fun resolveStatus(id: Long, status: PendingMutationStatus, drop: Boolean, freshToken: Long?, boundRequest: BoundLedgerRequest? = null): Boolean {
        val requeue = if (status == PendingMutationStatus.Conflict) dao::requeueConflictWithFreshToken
            else dao::requeueFailedWithFreshToken
        var expired = false
        val changed = bindingTransitionLease.withLock {
            val binding = canonicalBindingWithAliasesMigratedLocked(bindingProvider())
            boundRequest?.requireStillActiveFor(binding)
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
     * Binding source the live UI streams follow. A reactive [bindingChanges]
     * (AppContainer wires it from the active-ledger settings flow) and the
     * internal revision are invalidation signals only. Every emission re-reads
     * the authoritative binding under [bindingTransitionLease].
     */
    private fun bindingFlow(): Flow<OutboxBinding> {
        val invalidations = bindingChanges?.combine(bindingRevision) { _, revision ->
            revision
        } ?: bindingRevision
        return invalidations
            .map { currentBinding() }
            .distinctUntilChanged()
    }

    /**
     * Product-surface view of durable, unresolved intents for selected mutation
     * kinds. Completed rows are opt-in so a consumer can observe settlement even
     * when a fast Pending-to-Done transition was conflated by its UI collector.
     */
    @OptIn(ExperimentalCoroutinesApi::class)
    fun observeActiveByTypes(
        types: Set<PendingMutationType>,
        includeCompleted: Boolean = false,
    ): Flow<List<OutboxRow>> {
        val wireTypes = types
            .filterNot { it == PendingMutationType.Unknown }
            .map(PendingMutationType::wireValue)
        if (wireTypes.isEmpty()) return flowOf(emptyList())
        return bindingFlow().flatMapLatest { binding ->
            dao.observeActiveByTypes(
                ownerKey = binding.ownerStorageKey,
                ledgerId = binding.ledgerId,
                types = wireTypes,
                activeStatuses = if (includeCompleted) {
                    ACTIVE_STATUS_VALUES + PendingMutationStatus.Done.wireValue
                } else {
                    ACTIVE_STATUS_VALUES
                },
            )
        }.map { rows -> rows.map { it.toDomain() } }
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    fun observeStatus(): Flow<OutboxStatus> =
        bindingFlow().flatMapLatest { binding ->
            combine(
                dao.observeQueueDepth(
                    ownerKey = binding.ownerStorageKey,
                    ledgerId = binding.ledgerId,
                    pendingStatus = PendingMutationStatus.Pending.wireValue,
                    inFlightStatus = PendingMutationStatus.InFlight.wireValue,
                ),
                dao.observeConflictRows(
                    ownerKey = binding.ownerStorageKey,
                    ledgerId = binding.ledgerId,
                    conflictStatus = PendingMutationStatus.Conflict.wireValue,
                ),
                dao.observeFailedRows(
                    ownerKey = binding.ownerStorageKey,
                    ledgerId = binding.ledgerId,
                    failedStatus = PendingMutationStatus.Failed.wireValue,
                ),
                dao.observeQuarantinedCount(binding.owner?.storageKey),
            ) { queueDepth, conflicts, failed, quarantinedCount ->
                OutboxStatus(
                    binding = binding,
                    queueDepth = queueDepth,
                    conflicts = conflicts.map { it.toDomain() },
                    failed = failed.map { it.toDomain() },
                    quarantinedCount = quarantinedCount,
                )
            }.combine(writeBlock) { status, block -> status.copy(writeBlock = block) }
        }

    suspend fun activeForTarget(targetId: String): List<OutboxRow> =
        activeForTarget(currentBinding(), targetId)

    /** Only the Debt write owner can turn an unresolved command into a local stop. */
    internal suspend fun abandonDebtWrite(boundRequest: BoundLedgerRequest, row: OutboxRow): Boolean =
        withActiveBinding(boundRequest) { binding ->
            require(row.type in DEBT_WRITE_TYPES)
            dao.abandonDebtWrite(row.id, binding.ownerStorageKey, binding.ledgerId,
                row.status.wireValue, ISO.format(Instant.now(clock))) > 0
        }.also { changed -> if (changed) schedulePending() }

    /** Explicit Debt history scope; other mutation types retain their existing observation policy. */
    @OptIn(ExperimentalCoroutinesApi::class)
    internal fun observeDebtWrites(): Flow<List<OutboxRow>> = bindingFlow().flatMapLatest { binding ->
        dao.observeActiveByTypes(
            ownerKey = binding.ownerStorageKey,
            ledgerId = binding.ledgerId,
            types = DEBT_WRITE_TYPES.map { it.wireValue },
            activeStatuses = ACTIVE_STATUS_VALUES + listOf(PendingMutationStatus.Done.wireValue,
                PendingMutationStatus.Abandoned.wireValue),
        )
    }.map { rows -> rows.map { it.toDomain() } }

    internal suspend fun activeForTarget(
        boundRequest: BoundLedgerRequest,
        targetId: String,
    ): List<OutboxRow> = withActiveBinding(boundRequest) { binding ->
        activeForTarget(binding, targetId)
    }

    private suspend fun activeForTarget(
        binding: OutboxBinding,
        targetId: String,
        statuses: List<String> = ACTIVE_STATUS_VALUES,
    ): List<OutboxRow> = dao.activeForTarget(
        ownerKey = binding.ownerStorageKey,
        ledgerId = binding.ledgerId,
        targetId = targetId,
        activeStatuses = statuses,
    ).map { it.toDomain() }

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
        val removed = dao.deleteResolvedBefore(
            doneStatus = PendingMutationStatus.Done.wireValue,
            cutoffIso = ISO.format(cutoff),
        )
        notifyRowsDeleted(removed)
        return removed
    }

    /**
     * ADR-0042 §4.10 reaper: terminally FAIL every PENDING row enqueued more than
     * [OUTBOX_PENDING_AGE_CAP_MILLIS] ago WITHOUT replaying it, and return how
     * many rows were reaped.
     *
     * The drain engine calls this at the start of every pass. A row that's been
     * PENDING past the cap can no longer rely on its idempotency key (the server
     * has likely purged it — see [OUTBOX_PENDING_AGE_CAP_MILLIS]), so replaying it
     * risks a double-apply. Flipping it to FAILED here means [dequeueNextRunnable]
     * will never hand it to a dispatcher; instead it surfaces in the
     * "manual retry / drop" banner via [observeStatus] with the
     * ``outbox_row_expired`` marker, and the user redoes the action by hand
     * against fresh server state.
     *
     * **Global, not binding-scoped** (unlike the drain reads): a stale PENDING row
     * under ANY binding becomes a double-apply risk as soon as that binding is
     * active again, so the reap intentionally ignores ``serverUrl`` / ``ledgerId``
     * — same global reach as [gcCompleted] / [clearAll]. The DAO's
     * ``status = 'pending'`` guard keeps it from touching IN_FLIGHT / CONFLICT /
     * FAILED / DONE rows.
     *
     * [nowMillis] is injected (the engine passes its lambda clock) so the cap can
     * be exercised deterministically in a JVM unit test.
     *
     * @return the number of expired PENDING rows reaped to FAILED.
     */
    suspend fun reapExpiredPending(nowMillis: Long): Int {
        val cutoff = Instant.ofEpochMilli(nowMillis - OUTBOX_PENDING_AGE_CAP_MILLIS)
        return dao.markExpiredPendingAsFailed(
            cutoffCreatedAtIso = ISO.format(cutoff),
            status = PendingMutationStatus.Failed.wireValue,
            // Structured marker (snake_case, like recovered_from_stuck_in_flight /
            // no_dispatcher_registered:): SyncStatusScreen.friendlyLastError maps it
            // to user-facing copy. Never the raw key/timestamp — §10 jargon rule.
            lastError = "outbox_row_expired",
        )
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
    private suspend fun expireOverAgeOnResolve(
        id: Long,
        binding: OutboxBinding,
        fromStatus: String,
    ): Boolean {
        val cutoff = ISO.format(Instant.now(clock).minusMillis(OUTBOX_PENDING_AGE_CAP_MILLIS))
        return dao.expireBoundRowIfStatusAndOverAge(
            id = id,
            ownerKey = binding.ownerStorageKey,
            ledgerId = binding.ledgerId,
            fromStatus = fromStatus,
            cutoffCreatedAtIso = cutoff,
        ) > 0
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
        private val UNRESOLVED_STATUS_VALUES = listOf(
            PendingMutationStatus.InFlight.wireValue,
            PendingMutationStatus.Conflict.wireValue,
            PendingMutationStatus.Failed.wireValue,
        )
        private val ACTIVE_STATUS_VALUES = listOf(
            PendingMutationStatus.Pending.wireValue,
            PendingMutationStatus.InFlight.wireValue,
            PendingMutationStatus.Conflict.wireValue,
            PendingMutationStatus.Failed.wireValue,
        )
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
    val ownerKey: String? = null,
    val type: PendingMutationType,
    val targetId: String,
    val payloadJson: String,
    val expectedRowVersion: Long,
    val status: PendingMutationStatus,
    val retryCount: Int,
    val lastError: String?,
    val createdAt: String,
    val attemptedAt: String?,
    val completedAt: String?,
    val idempotencyKey: String? = null,
    val receiptJson: String? = null,
    val blocksFollowing: Boolean = true,
)

internal fun OutboxRow.bindingOrNull(): OutboxBinding? {
    val owner = OutboxOwnerIdentity.parseOrNull(ownerKey) ?: return null
    val canonicalOrigin = canonicalServerOriginOrNull(serverUrl) ?: return null
    val cleanLedgerId = ledgerId.trim().takeIf(String::isNotEmpty) ?: return null
    return OutboxBinding(
        serverUrl = canonicalOrigin,
        ledgerId = cleanLedgerId,
        owner = owner,
    )
}

data class OutboxBinding(
    val serverUrl: String,
    val ledgerId: String,
    val owner: OutboxOwnerIdentity?,
) {
    internal val ownerStorageKey: String
        get() = owner?.storageKey.orEmpty()

    internal fun trimmed(): OutboxBinding =
        OutboxBinding(
            serverUrl = serverUrl.trim().trimEnd('/'),
            ledgerId = ledgerId.trim(),
            owner = owner,
        )

    fun normalized(): OutboxBinding {
        val trimmed = trimmed()
        return trimmed.copy(
            serverUrl = canonicalServerOriginOrNull(trimmed.serverUrl) ?: trimmed.serverUrl,
        )
    }

    internal fun requireReadyForEnqueue() {
        if (serverUrl.isBlank() || ledgerId.isBlank() || owner == null) {
            throw RepositoryException("设备身份尚未完成校验，已停止保存离线操作。")
        }
    }

    companion object {
        val DEFAULT = OutboxBinding(serverUrl = "", ledgerId = "", owner = null)
    }
}

data class OutboxServerAliasMigration(
    val oldServerUrl: String,
    val newServerUrl: String,
    val ledgerId: String,
) {
    init {
        val oldCanonical = canonicalServerOriginOrNull(oldServerUrl)
        require(
            ledgerId.isNotBlank() &&
                oldCanonical != null &&
                oldCanonical == newServerUrl &&
                oldCanonical == canonicalServerOriginOrNull(newServerUrl),
        ) {
            "Outbox rows may only migrate between aliases of one canonical origin."
        }
    }
}

data class OutboxStatus(
    val queueDepth: Int,
    val conflicts: List<OutboxRow>,
    val failed: List<OutboxRow>,
    val quarantinedCount: Int = 0,
    val writeBlock: OutboxWriteBlock? = null,
    val binding: OutboxBinding? = null,
) {
    val needsUserAction: Boolean
        get() = conflicts.isNotEmpty() || failed.isNotEmpty() || quarantinedCount > 0
}

enum class OutboxWriteBlock {
    CURRENCY_ADOPTION_REQUIRED,
}

internal fun PendingMutationEntity.toDomain(): OutboxRow = OutboxRow(
    id = id,
    serverUrl = serverUrl,
    ledgerId = ledgerId,
    ownerKey = ownerKey,
    type = PendingMutationType.fromWire(type),
    targetId = targetId,
    payloadJson = payload,
    expectedRowVersion = expectedRowVersion,
    status = PendingMutationStatus.fromWire(status),
    retryCount = retryCount,
    lastError = lastError,
    createdAt = createdAt,
    attemptedAt = attemptedAt,
    completedAt = completedAt,
    idempotencyKey = idempotencyKey,
    receiptJson = receiptJson,
    blocksFollowing = blocksFollowing,
)

/**
 * User-facing branch on a CONFLICT row. The "keep mine" branch
 * needs a freshly-fetched token from the call site (the previous
 * one is by definition stale).
 */
sealed interface ConflictResolution {
    data class KeepMine(val freshToken: Long) : ConflictResolution
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
    data class Retry(val freshToken: Long? = null) : FailedResolution
    data object Drop : FailedResolution
}

package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationDao
import com.ticketbox.data.local.PendingMutationEntity
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flowOf
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
     * Hold the dispatch lease across the epoch check and
     * [OutboxDrainEngine.drainOnce] dispatch so a binding transition cannot
     * change credentials between claim and send. [withBindingTransition]
     * takes the same lease for the epoch bump and credential writes.
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
            validateTargetRows?.invoke(dao.expenseAdmissionRows(binding, intent.targetId, activeForTarget(binding, intent.targetId,
                ACTIVE_STATUS_VALUES + PendingMutationStatus.Done.wireValue)))
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

    /** Save+confirm and ready-bulk preserve every original before any worker may send. */
    internal suspend fun enqueueExpenseBatch(
        boundRequest: BoundLedgerRequest,
        intents: List<PendingMutationIntent>,
        validateTargetRows: (List<OutboxRow>) -> Unit,
    ): List<Long> {
        val ids = withActiveBinding(boundRequest) { binding ->
            binding.requireReadyForEnqueue()
            dao.insertExpenseCommands(binding, intents, nowIso(), validateTargetRows)
        }
        schedulePending()
        return ids
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
                        if (dao.expireBoundIfOverAge(row.id, binding, PendingMutationStatus.Failed.wireValue, overAgeCutoffIso())) {
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

    private suspend fun notifyRowsDeleted(removed: Int) {
        if (removed <= 0) return
        try {
            onRowsDeleted()
        } catch (error: CancellationException) {
            throw error
        } catch (_: Exception) {
        }
    }

    private fun notifyClearBoundary() {
        try {
            onClearAll()
        } catch (_: Exception) {
        }
    }

    private fun bindingFlow(): Flow<OutboxBinding> {
        val invalidations = bindingChanges?.combine(bindingRevision) { _, revision ->
            revision
        } ?: bindingRevision
        return invalidations.map { currentBinding() }.distinctUntilChanged()
    }

    suspend fun dequeueNextRunnable(limit: Int = DEFAULT_DRAIN_BATCH, excludedIds: List<Long> = emptyList()): List<OutboxRow> =
        dao.nextRunnableRows(currentBinding(), UNRESOLVED_STATUS_VALUES, limit, excludedIds)

    suspend fun recoverStaleInFlight(staleAfterMillis: Long = DEFAULT_STALE_IN_FLIGHT_MS): Int {
        val binding = currentBinding()
        return dao.recoverStaleInFlight(
            ownerKey = binding.ownerStorageKey,
            ledgerId = binding.ledgerId,
            staleCutoffIso = ISO.format(Instant.now(clock).minusMillis(staleAfterMillis)),
            recoveryMessage = "recovered_from_stuck_in_flight",
        )
    }

    suspend fun tryClaim(id: Long): Boolean =
        dao.markInFlightIfPending(id, PendingMutationStatus.Pending.wireValue, PendingMutationStatus.InFlight.wireValue, nowIso()) > 0

    suspend fun markDone(id: Long, cacheRefreshVersion: Long? = null, receiptJson: String? = null) {
        dao.markDone(id, PendingMutationStatus.Done.wireValue, nowIso(), cacheRefreshVersion?.let { "$EXPENSE_REFRESH_PREFIX$it" }, receiptJson)
    }

    internal suspend fun acknowledgeExpenseRefresh(boundRequest: BoundLedgerRequest, versions: Map<Long, Long>) =
        bindingTransitionLease.withLock {
            val binding = canonicalBindingWithAliasesMigratedLocked(bindingProvider())
            try {
                boundRequest.requireStillActiveFor(binding)
            } catch (_: RepositoryException) {
                return@withLock
            }
            dao.clearAdoptedExpenseRefreshes(binding, versions)
        }

    suspend fun cascadeFreshToken(targetId: String, newToken: Long): Int =
        dao.cascadePreservedTokens(currentBinding(), targetId, newToken)
    suspend fun markRetryable(id: Long, error: String) {
        dao.markRetryable(id, PendingMutationStatus.Pending.wireValue, error)
    }
    internal suspend fun revertClaimWithoutAttempt(id: Long) {
        dao.revertClaimWithoutAttempt(id, PendingMutationStatus.Pending.wireValue, PendingMutationStatus.InFlight.wireValue)
    }
    suspend fun markConflict(id: Long, serverMessage: String) {
        dao.markConflict(id, PendingMutationStatus.Conflict.wireValue, serverMessage)
    }
    suspend fun markFailed(id: Long, error: String, blocksFollowing: Boolean = true) {
        dao.markFailed(id, PendingMutationStatus.Failed.wireValue, error, blocksFollowing)
    }
    suspend fun reapExpiredPending(nowMillis: Long): Int =
        dao.reapExpiredPendingRows(ISO.format(Instant.ofEpochMilli(nowMillis - OUTBOX_PENDING_AGE_CAP_MILLIS)))

    suspend fun clearAll(): Int {
        val removed = withBindingTransition(clearExistingRows = false) { dao.clearAll() }
        notifyRowsDeleted(removed)
        return removed
    }

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

    internal suspend fun discardOriginalExpense(
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

    internal suspend fun resolveConflict(id: Long, resolution: ConflictResolution, boundRequest: BoundLedgerRequest? = null): Boolean =
        resolveStatus(id, PendingMutationStatus.Conflict, resolution == ConflictResolution.DropMine,
            (resolution as? ConflictResolution.KeepMine)?.freshToken, boundRequest)

    internal suspend fun resolveFailed(id: Long, resolution: FailedResolution, boundRequest: BoundLedgerRequest? = null): Boolean =
        resolveStatus(id, PendingMutationStatus.Failed, resolution == FailedResolution.Drop,
            (resolution as? FailedResolution.Retry)?.freshToken, boundRequest)

    internal suspend fun discardCompletedOriginalSubmission(boundRequest: BoundLedgerRequest, row: OutboxRow): Boolean {
        require(row.type in setOf(PendingMutationType.CreateIncomePlan, PendingMutationType.UpdateIncomePlan,
            PendingMutationType.SaveManualExchangeRate))
        require(row.status == PendingMutationStatus.Done)
        boundRequest.requireStillActiveFor(requireNotNull(row.bindingOrNull()))
        return resolveStatus(row.id, PendingMutationStatus.Done, true, null, boundRequest)
    }

    private suspend fun resolveStatus(id: Long, status: PendingMutationStatus, drop: Boolean, freshToken: Long?, boundRequest: BoundLedgerRequest? = null): Boolean {
        val requeue = if (status == PendingMutationStatus.Conflict) dao::requeueConflictWithFreshToken
            else dao::requeueFailedWithFreshToken
        var expired = false
        val changed = bindingTransitionLease.withLock {
            val binding = canonicalBindingWithAliasesMigratedLocked(bindingProvider())
            boundRequest?.requireStillActiveFor(binding)
            if (!drop && dao.refusesExpenseRecovery(binding, id, status, freshToken)) return@withLock false
            when {
                drop -> dao.deleteIfStatus(id, binding.ownerStorageKey, binding.ledgerId, status.wireValue) > 0
                dao.expireBoundIfOverAge(id, binding, status.wireValue, overAgeCutoffIso()) -> {
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

    suspend fun gcCompleted(retentionMillis: Long = DEFAULT_RETENTION_MS): Int {
        val removed = dao.deleteResolvedBeforeCutoff(ISO.format(Instant.now(clock).minusMillis(retentionMillis)))
        notifyRowsDeleted(removed)
        return removed
    }

    private fun overAgeCutoffIso(): String =
        ISO.format(Instant.now(clock).minusMillis(OUTBOX_PENDING_AGE_CAP_MILLIS))

    internal suspend fun replaceCreateExpensePayload(id: Long, payloadJson: String): Boolean =
        dao.replacePayload(id, PendingMutationType.CreateExpense.wireValue, payloadJson) == 1

    fun observeActiveByTypes(types: Set<PendingMutationType>, includeCompleted: Boolean = false): Flow<List<OutboxRow>> {
        val wireTypes = types.filterNot { it == PendingMutationType.Unknown }.map(PendingMutationType::wireValue)
        val statuses = if (includeCompleted) ACTIVE_STATUS_VALUES + PendingMutationStatus.Done.wireValue else ACTIVE_STATUS_VALUES
        return observeBoundActiveRows(dao, bindingFlow(), wireTypes, statuses)
    }

    fun observeStatus(): Flow<OutboxStatus> = observeBoundOutboxStatus(dao, bindingFlow(), writeBlock)

    suspend fun activeForTarget(targetId: String): List<OutboxRow> =
        dao.activeRowsForTarget(currentBinding(), targetId, ACTIVE_STATUS_VALUES)

    internal suspend fun abandonDebtWrite(boundRequest: BoundLedgerRequest, row: OutboxRow): Boolean =
        withActiveBinding(boundRequest) { binding ->
            require(row.type in DEBT_WRITE_TYPES)
            dao.abandonDebtWrite(row.id, binding.ownerStorageKey, binding.ledgerId,
                row.status.wireValue, ISO.format(Instant.now(clock))) > 0
        }.also { changed -> if (changed) schedulePending() }

    internal fun observeDebtWrites(): Flow<List<OutboxRow>> = observeBoundDebtWrites(
        dao,
        bindingFlow(),
        ACTIVE_STATUS_VALUES + listOf(PendingMutationStatus.Done.wireValue, PendingMutationStatus.Abandoned.wireValue),
    )

    internal suspend fun activeForTarget(boundRequest: BoundLedgerRequest, targetId: String): List<OutboxRow> =
        withActiveBinding(boundRequest) { binding -> activeForTarget(binding, targetId) }

    private suspend fun activeForTarget(
        binding: OutboxBinding,
        targetId: String,
        statuses: List<String> = ACTIVE_STATUS_VALUES,
    ): List<OutboxRow> = dao.activeRowsForTarget(binding, targetId, statuses)

    private fun nowIso(): String = ISO.format(Instant.now(clock))

    companion object {
        /** Fixed-width UTC text so SQLite lex order matches createdAt time order. */
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
    val refreshRequired: List<OutboxRow> = emptyList(),
) {
    val needsUserAction: Boolean
        get() = conflicts.isNotEmpty() || failed.isNotEmpty() || quarantinedCount > 0 || refreshRequired.isNotEmpty()
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

/** Runs under the existing binding lease before the single Room batch transaction. */
private suspend fun PendingMutationDao.insertExpenseCommands(
    binding: OutboxBinding,
    intents: List<PendingMutationIntent>,
    createdAt: String,
    validateTargetRows: (List<OutboxRow>) -> Unit,
): List<Long> {
    require(intents.isNotEmpty() && intents.all { it.type in PENDING_EXPENSE_COMMAND_TYPES })
    for (targetId in intents.map { it.targetId }.distinct()) {
        val targetRows = activeForTarget(binding.ownerStorageKey, binding.ledgerId, targetId,
            listOf(PendingMutationStatus.Pending, PendingMutationStatus.InFlight, PendingMutationStatus.Conflict,
                PendingMutationStatus.Failed, PendingMutationStatus.Done).map { it.wireValue }).map { it.toDomain() }
        validateTargetRows(expenseAdmissionRows(binding, targetId, targetRows))
    }
    return insertBatch(intents.map { it.toEntity(binding, createdAt) })
}

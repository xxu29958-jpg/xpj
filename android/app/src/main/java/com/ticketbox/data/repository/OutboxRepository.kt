package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationDao
import com.ticketbox.data.local.PendingMutationEntity
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.update
import java.time.Clock
import java.time.Instant

class OutboxRepository private constructor(
    private val dao: PendingMutationDao,
    private val clock: Clock,
    bindingSource: OutboxBindingSource,
    lifecycleHooks: OutboxLifecycleHooks,
    private val writeBlock: Flow<OutboxWriteBlock?>,
) {
    private val onEnqueued = lifecycleHooks.onEnqueued
    private val onClearAll = lifecycleHooks.onClearAll
    private val onRowsDeleted = lifecycleHooks.onRowsDeleted

    private val binding = OutboxBindingCoordinator(
        dao = dao,
        bindingSource = bindingSource,
        onClearBoundary = ::notifyClearBoundary,
        onRowsDeleted = ::notifyRowsDeleted,
    )
    private val settlement = OutboxSettlementCoordinator(
        dao = dao,
        binding = binding,
        clock = clock,
        onSchedulePending = ::schedulePending,
        onRowsDeleted = ::notifyRowsDeleted,
    )

    private val mutableAcceptedReplayRevision = MutableStateFlow(0L)
    val acceptedReplayRevision: StateFlow<Long> = mutableAcceptedReplayRevision.asStateFlow()
    internal fun noteAcceptedReplay() = mutableAcceptedReplayRevision.update { it + 1L }

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

    fun currentSessionEpoch(): Long = binding.currentSessionEpoch()

    internal fun bumpSessionEpochForTesting() = binding.bumpSessionEpochForTesting()

    suspend fun <T> withDispatchLease(block: suspend () -> T): T = binding.withDispatchLease(block)

    internal suspend fun <T> withActiveBinding(
        boundRequest: BoundLedgerRequest,
        block: suspend (OutboxBinding) -> T,
    ): T = binding.withActiveBinding(boundRequest, block)

    suspend fun <T> withBindingTransition(
        clearExistingRows: Boolean = false,
        serverAliasMigration: OutboxServerAliasMigration? = null,
        block: suspend () -> T,
    ): T = binding.withBindingTransition(clearExistingRows, serverAliasMigration, block)

    suspend fun enqueue(
        type: PendingMutationType,
        targetId: String,
        payloadJson: String,
        expectedRowVersion: Long,
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

    internal suspend fun enqueue(
        boundRequest: BoundLedgerRequest?,
        intent: PendingMutationIntent,
        validateTargetRows: ((List<OutboxRow>) -> Unit)? = null,
        afterPersisted: suspend () -> Unit = {},
    ): Long {
        val id = binding.withBindingLock { current ->
            boundRequest?.requireStillActiveFor(current)
            current.requireReadyForEnqueue()
            validateTargetRows?.invoke(
                dao.expenseAdmissionRows(
                    current,
                    intent.targetId,
                    activeForTarget(current, intent.targetId, ACTIVE_STATUS_VALUES + PendingMutationStatus.Done.wireValue),
                ),
            )
            dao.insertAndPublish(intent.toEntity(current, clock.outboxNowIso()), afterPersisted)
        }
        schedulePending()
        return id
    }

    internal fun schedulePending() {
        try {
            onEnqueued()
        } catch (_: Exception) {
        }
    }

    internal suspend fun enqueueOriginalCreation(boundRequest: BoundLedgerRequest, intent: PendingMutationIntent): Long {
        require(
            intent.type in setOf(
                PendingMutationType.FinancialAccountCommand,
                PendingMutationType.CreateIncomePlan,
                PendingMutationType.CreateGoal,
                PendingMutationType.CapturePaymentNotification,
                PendingMutationType.CreateDebt,
                PendingMutationType.AcceptBillSplitInvitation,
            ),
        )
        val id = withActiveBinding(boundRequest) { current ->
            current.requireReadyForEnqueue()
            dao.insertOriginalCreation(intent.toEntity(current, clock.outboxNowIso()))
        }
        schedulePending()
        return id
    }

    internal suspend fun originalCreation(boundRequest: BoundLedgerRequest, key: String, type: PendingMutationType): OutboxRow? =
        withActiveBinding(boundRequest) { current ->
            require(type in setOf(PendingMutationType.CreateIncomePlan, PendingMutationType.CreateDebt))
            val rows = dao.findByIdempotencyKeys(current.ownerStorageKey, current.ledgerId, type.wireValue, listOf(key))
            val row = rows.singleOrNull()
            require(rows.size <= 1 && (row == null || row.serverUrl == current.serverUrl)) {
                "原创建归属无法确认，请先核对原提交。"
            }
            row?.toDomain()
        }

    internal suspend fun enqueueNotificationSnapshot(
        boundRequest: BoundLedgerRequest,
        snapshots: com.ticketbox.data.local.NotificationSnapshotDao,
        delivery: NotificationSnapshotDelivery,
        plan: (com.ticketbox.data.local.NotificationSnapshotEntity?, OutboxRow?) -> NotificationSnapshotAdmission,
    ): Long {
        val id = withActiveBinding(boundRequest) { current ->
            current.requireReadyForEnqueue()
            snapshots.acceptNotificationSnapshot(delivery.slotKey, delivery.key) { previous, original ->
                val admission = plan(previous, original?.toDomain())
                val savedId = admission.intent?.let { dao.insert(it.toEntity(current, clock.outboxNowIso())) }
                    ?: admission.snapshot.originalId
                require(savedId > 0)
                admission.snapshot.copy(originalId = savedId)
            }
        }
        schedulePending()
        return id
    }

    internal suspend fun enqueueExpenseBatch(
        boundRequest: BoundLedgerRequest,
        intents: List<PendingMutationIntent>,
        afterPersisted: suspend () -> Unit = {},
        validateTargetRows: (List<OutboxRow>) -> Unit,
    ): List<Long> {
        val ids = withActiveBinding(boundRequest) { current ->
            current.requireReadyForEnqueue()
            dao.insertExpenseCommands(current, intents, clock.outboxNowIso(), validateTargetRows, afterPersisted)
        }
        schedulePending()
        return ids
    }

    internal suspend fun enqueueUploadBatch(
        boundRequest: BoundLedgerRequest,
        intents: List<PendingMutationIntent>,
        afterPersisted: (suspend () -> Unit)? = null,
    ): List<Long> {
        require(intents.size in 1..100)
        require(intents.map { it.type }.distinct().size == 1)
        require(
            intents.all {
                (it.type in setOf(PendingMutationType.UploadScreenshot, PendingMutationType.CaptureDebtBill) && it.expectedRowVersion == 0L) ||
                    (it.type == PendingMutationType.OriginalAttachment && it.expectedRowVersion > 0L)
            },
        )
        val keys = intents.map { requireNotNull(it.idempotencyKey) }
        require(keys.distinct().size == keys.size && keys.all(::isUploadIntentFileKey))
        val ids = withActiveBinding(boundRequest) { current ->
            current.requireReadyForEnqueue()
            val existing = dao.findByIdempotencyKeys(current.ownerStorageKey, current.ledgerId, intents.first().type.wireValue, keys)
            if (existing.isNotEmpty()) {
                check(existing.size == intents.size) { "Incomplete original upload acceptance" }
                val byKey = existing.associateBy { it.idempotencyKey }
                intents.map { intent ->
                    val row = checkNotNull(byKey[intent.idempotencyKey])
                    check(
                        row.payload == intent.payloadJson &&
                            row.targetId == intent.targetId &&
                            row.expectedRowVersion == intent.expectedRowVersion,
                    ) { "Original upload intent changed" }
                    row.id
                }
            } else {
                val createdAt = clock.outboxNowIso()
                val rows = intents.map { it.toEntity(current, createdAt) }
                if (afterPersisted == null) dao.insertBatch(rows) else dao.insertBatchAndPublish(rows, afterPersisted)
            }
        }
        schedulePending()
        return ids
    }

    internal suspend fun originalUploadRows(
        boundRequest: BoundLedgerRequest,
        keys: List<String>,
        type: PendingMutationType = PendingMutationType.UploadScreenshot,
    ): List<OutboxRow> = withActiveBinding(boundRequest) { current ->
        dao.findByIdempotencyKeys(current.ownerStorageKey, current.ledgerId, type.wireValue, keys).map { it.toDomain() }
    }

    internal suspend fun allRowsForUploadFileReferences(): List<PendingMutationEntity> = dao.allRows()

    internal suspend fun recoverUploadGroup(
        boundRequest: BoundLedgerRequest,
        targetId: String,
        drop: Boolean,
        retryIds: List<Long> = emptyList(),
    ): Boolean = settlement.recoverUploadGroup(boundRequest, targetId, drop, retryIds)

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

    suspend fun dequeueNextRunnable(limit: Int = DEFAULT_DRAIN_BATCH, excludedIds: List<Long> = emptyList()): List<OutboxRow> =
        dao.nextRunnableRows(binding.currentBinding(), UNRESOLVED_STATUS_VALUES, limit, excludedIds)

    suspend fun recoverStaleInFlight(staleAfterMillis: Long = DEFAULT_STALE_IN_FLIGHT_MS): Int {
        val current = binding.currentBinding()
        return dao.recoverStaleInFlight(
            ownerKey = current.ownerStorageKey,
            ledgerId = current.ledgerId,
            staleCutoffIso = OUTBOX_ISO_FORMATTER.format(Instant.now(clock).minusMillis(staleAfterMillis)),
            recoveryMessage = "recovered_from_stuck_in_flight",
        )
    }

    suspend fun tryClaim(id: Long): Boolean =
        dao.markInFlightIfPending(id, PendingMutationStatus.Pending.wireValue, PendingMutationStatus.InFlight.wireValue, clock.outboxNowIso()) > 0

    internal var onDebtDispatchPreparing: suspend (OutboxRow) -> Unit
        get() = settlement.onDebtDispatchPreparing
        set(value) { settlement.onDebtDispatchPreparing = value }
    internal var onDebtDispatchFinished: suspend (OutboxRow, DispatchResult?) -> Unit
        get() = settlement.onDebtDispatchFinished
        set(value) { settlement.onDebtDispatchFinished = value }
    internal var onDebtAccepted: suspend (OutboxRow) -> Unit
        get() = settlement.onDebtAccepted
        set(value) { settlement.onDebtAccepted = value }

    internal var onRecurringDispatchPreparing: suspend (OutboxRow) -> Unit
        get() = settlement.onRecurringDispatchPreparing
        set(value) { settlement.onRecurringDispatchPreparing = value }
    internal var onRecurringDispatchFinished: suspend (OutboxRow, DispatchResult?) -> Unit
        get() = settlement.onRecurringDispatchFinished
        set(value) { settlement.onRecurringDispatchFinished = value }
    internal var onRecurringAccepted: suspend (OutboxRow) -> Unit
        get() = settlement.onRecurringAccepted
        set(value) { settlement.onRecurringAccepted = value }

    internal var onIncomeDispatchPreparing: suspend (OutboxRow) -> Unit
        get() = settlement.onIncomeDispatchPreparing
        set(value) { settlement.onIncomeDispatchPreparing = value }
    internal var onIncomeDispatchFinished: suspend (OutboxRow, DispatchResult?) -> Unit
        get() = settlement.onIncomeDispatchFinished
        set(value) { settlement.onIncomeDispatchFinished = value }
    internal var onIncomeAccepted: suspend (OutboxRow) -> Unit
        get() = settlement.onIncomeAccepted
        set(value) { settlement.onIncomeAccepted = value }

    internal fun affectsRecurringReads(row: OutboxRow): Boolean = row.affectsRecurringReads()

    internal suspend fun prepareReadProtection(row: OutboxRow) = settlement.prepareReadProtection(row)

    internal suspend fun finishReadProtection(row: OutboxRow, result: DispatchResult?) =
        settlement.finishReadProtection(row, result)

    suspend fun markDone(
        id: Long,
        cacheRefreshVersion: Long? = null,
        receiptJson: String? = null,
    ): Boolean = settlement.markDone(
        id = id,
        settlement = OutboxDoneSettlement(
            cacheRefreshVersion = cacheRefreshVersion,
            receiptJson = receiptJson,
        ),
    )

    internal suspend fun markDone(id: Long, settlement: OutboxDoneSettlement): Boolean =
        this.settlement.markDone(id, settlement)

    internal suspend fun recoverBudgetReadRefresh(
        bound: BoundLedgerRequest,
        month: String,
        cleanup: suspend (OutboxRow) -> Unit,
    ) = settlement.recoverBudgetReadRefresh(bound, month, cleanup)

    internal suspend fun acknowledgeRuleApplicationRefresh(bound: BoundLedgerRequest, original: OutboxRow) =
        settlement.acknowledgeRuleApplicationRefresh(bound, original)

    internal suspend fun acknowledgeExpenseRefresh(boundRequest: BoundLedgerRequest, versions: Map<Long, Long>) =
        settlement.acknowledgeExpenseRefresh(boundRequest, versions)

    suspend fun cascadeFreshToken(targetId: String, newToken: Long): Int =
        dao.cascadePreservedTokens(binding.currentBinding(), targetId, newToken)

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
        dao.reapExpiredPendingRows(OUTBOX_ISO_FORMATTER.format(Instant.ofEpochMilli(nowMillis - OUTBOX_PENDING_AGE_CAP_MILLIS)))

    suspend fun clearAll(): Int {
        val removed = withBindingTransition(clearExistingRows = false) { dao.clearAll() }
        notifyRowsDeleted(removed)
        return removed
    }

    suspend fun clearQuarantined(): Int {
        val removed = binding.withDispatchLease {
            binding.withBindingLock { current ->
                current.requireReadyForEnqueue()
                dao.deleteQuarantined(current.ownerStorageKey)
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
    ): Boolean = settlement.discardOriginalExpense(boundRequest, row, afterDeleted)

    internal suspend fun resolveConflict(id: Long, resolution: ConflictResolution, boundRequest: BoundLedgerRequest? = null): Boolean =
        settlement.resolveStatus(
            id,
            PendingMutationStatus.Conflict,
            resolution == ConflictResolution.DropMine,
            (resolution as? ConflictResolution.KeepMine)?.freshToken,
            boundRequest,
        )

    internal suspend fun resolveFailed(id: Long, resolution: FailedResolution, boundRequest: BoundLedgerRequest? = null): Boolean =
        settlement.resolveStatus(
            id,
            PendingMutationStatus.Failed,
            resolution == FailedResolution.Drop,
            (resolution as? FailedResolution.Retry)?.freshToken,
            boundRequest,
        )

    internal suspend fun discardCompletedOriginalSubmission(boundRequest: BoundLedgerRequest, row: OutboxRow): Boolean {
        require(
            row.type in setOf(
                PendingMutationType.CreateIncomePlan,
                PendingMutationType.UpdateIncomePlan,
                PendingMutationType.SaveManualExchangeRate,
            ),
        )
        require(row.status == PendingMutationStatus.Done)
        boundRequest.requireStillActiveFor(requireNotNull(row.bindingOrNull()))
        return settlement.resolveStatus(row.id, PendingMutationStatus.Done, true, null, boundRequest)
    }

    internal suspend fun replaceCreateExpensePayload(id: Long, payloadJson: String): Boolean =
        dao.replacePayload(id, PendingMutationType.CreateExpense.wireValue, payloadJson) == 1

    fun observeActiveByTypes(
        types: Set<PendingMutationType>,
        includeCompleted: Boolean = false,
        includeAbandoned: Boolean = false,
    ): Flow<List<OutboxRow>> {
        val wireTypes = types.filterNot { it == PendingMutationType.Unknown }.map(PendingMutationType::wireValue)
        val statuses = buildList {
            addAll(ACTIVE_STATUS_VALUES)
            if (includeCompleted) add(PendingMutationStatus.Done.wireValue)
            if (includeAbandoned) add(PendingMutationStatus.Abandoned.wireValue)
        }
        return observeBoundActiveRows(dao, binding.bindingFlow(), wireTypes, statuses)
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    internal fun observeOriginalCommand(
        type: PendingMutationType,
        idempotencyKey: String? = null,
        originalId: Long? = null,
    ): Flow<List<OutboxRow>> {
        require((idempotencyKey != null) != (originalId != null)) { "请选择一份原提交。" }
        return binding.bindingFlow().flatMapLatest { current ->
            val originals = if (originalId != null) {
                dao.observeOriginalCommandById(current.serverUrl, current.ownerStorageKey, current.ledgerId, type.wireValue, originalId)
            } else {
                dao.observeOriginalCommand(current.serverUrl, current.ownerStorageKey, current.ledgerId, type.wireValue, requireNotNull(idempotencyKey))
            }
            originals.map { rows -> rows.map { it.toDomain() } }
        }
    }

    fun observeStatus(): Flow<OutboxStatus> = observeBoundOutboxStatus(dao, binding.bindingFlow(), writeBlock)

    suspend fun activeForTarget(targetId: String): List<OutboxRow> =
        dao.activeRowsForTarget(binding.currentBinding(), targetId, ACTIVE_STATUS_VALUES)

    internal suspend fun abandonOriginalCommand(boundRequest: BoundLedgerRequest, row: OutboxRow): Boolean =
        withActiveBinding(boundRequest) { current ->
            require(
                row.type in DEBT_WRITE_TYPES || row.type in setOf(
                    PendingMutationType.CreateGoal,
                    PendingMutationType.DismissRepaymentDraft,
                    PendingMutationType.ResolvePaymentCapture,
                ),
            )
            dao.abandonOriginalCommand(
                row.id,
                current.ownerStorageKey,
                current.ledgerId,
                row.status.wireValue,
                clock.outboxNowIso(),
            ) > 0
        }.also { changed -> if (changed) schedulePending() }

    internal fun observeDebtWrites(): Flow<List<OutboxRow>> = observeBoundDebtWrites(
        dao,
        binding.bindingFlow(),
        ACTIVE_STATUS_VALUES + listOf(PendingMutationStatus.Done.wireValue, PendingMutationStatus.Abandoned.wireValue),
    )

    internal suspend fun activeForTarget(boundRequest: BoundLedgerRequest, targetId: String): List<OutboxRow> =
        withActiveBinding(boundRequest) { current -> activeForTarget(current, targetId) }

    private suspend fun activeForTarget(
        binding: OutboxBinding,
        targetId: String,
        statuses: List<String> = ACTIVE_STATUS_VALUES,
    ): List<OutboxRow> = dao.activeRowsForTarget(binding, targetId, statuses)

    companion object {
        const val DEFAULT_DRAIN_BATCH: Int = 25
        const val DEFAULT_STALE_IN_FLIGHT_MS: Long = 5L * 60L * 1000L
        internal val UNRESOLVED_STATUS_VALUES = listOf(
            PendingMutationStatus.InFlight.wireValue,
            PendingMutationStatus.Conflict.wireValue,
            PendingMutationStatus.Failed.wireValue,
        )
        internal val ACTIVE_STATUS_VALUES = listOf(
            PendingMutationStatus.Pending.wireValue,
            PendingMutationStatus.InFlight.wireValue,
            PendingMutationStatus.Conflict.wireValue,
            PendingMutationStatus.Failed.wireValue,
        )
    }
}

private suspend fun PendingMutationDao.insertExpenseCommands(
    binding: OutboxBinding,
    intents: List<PendingMutationIntent>,
    createdAt: String,
    validateTargetRows: (List<OutboxRow>) -> Unit,
    afterPersisted: suspend () -> Unit,
): List<Long> {
    require(intents.isNotEmpty() && intents.all { it.type in PENDING_EXPENSE_COMMAND_TYPES })
    for (targetId in intents.map { it.targetId }.distinct()) {
        val targetRows = activeForTarget(
            binding.ownerStorageKey,
            binding.ledgerId,
            targetId,
            listOf(
                PendingMutationStatus.Pending,
                PendingMutationStatus.InFlight,
                PendingMutationStatus.Conflict,
                PendingMutationStatus.Failed,
                PendingMutationStatus.Done,
            ).map { it.wireValue },
        ).map { it.toDomain() }
        validateTargetRows(expenseAdmissionRows(binding, targetId, targetRows))
    }
    return insertBatchAndPublish(intents.map { it.toEntity(binding, createdAt) }, afterPersisted)
}

package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationDao
import com.ticketbox.data.local.PendingMutationStatus
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map

/**
 * Status projection for [OutboxRepository].
 * Bindings are already linearized by the repository before these reads.
 */

@OptIn(ExperimentalCoroutinesApi::class)
internal fun observeBoundActiveRows(
    dao: PendingMutationDao,
    bindings: Flow<OutboxBinding>,
    types: List<String>,
    activeStatuses: List<String>,
): Flow<List<OutboxRow>> {
    if (types.isEmpty()) return flowOf(emptyList())
    return bindings.flatMapLatest { binding ->
        dao.observeActiveByTypes(
            ownerKey = binding.ownerStorageKey,
            ledgerId = binding.ledgerId,
            types = types,
            activeStatuses = activeStatuses,
        )
    }.map { rows -> rows.map { it.toDomain() } }
}

@OptIn(ExperimentalCoroutinesApi::class)
internal fun observeBoundOutboxStatus(
    dao: PendingMutationDao,
    bindings: Flow<OutboxBinding>,
    writeBlock: Flow<OutboxWriteBlock?>,
): Flow<OutboxStatus> = bindings.flatMapLatest { binding ->
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
        dao.observeExpenseRefreshRows(binding),
    ) { queueDepth, conflicts, failed, quarantinedCount, completed ->
        OutboxStatus(
            binding = binding,
            queueDepth = queueDepth,
            conflicts = conflicts.map { it.toDomain() },
            failed = failed.map { it.toDomain() },
            quarantinedCount = quarantinedCount,
            refreshRequired = completed.map { it.toDomain() }.filter { it.requiresExpenseRefresh() },
        )
    }.combine(writeBlock) { status, block -> status.copy(writeBlock = block) }
}

internal suspend fun PendingMutationDao.activeRowsForTarget(
    binding: OutboxBinding,
    targetId: String,
    statuses: List<String>,
): List<OutboxRow> = activeForTarget(
    ownerKey = binding.ownerStorageKey,
    ledgerId = binding.ledgerId,
    targetId = targetId,
    activeStatuses = statuses,
).map { it.toDomain() }

internal fun observeBoundDebtWrites(
    dao: PendingMutationDao,
    bindings: Flow<OutboxBinding>,
    activeStatuses: List<String>,
): Flow<List<OutboxRow>> = observeBoundActiveRows(
    dao,
    bindings,
    DEBT_WRITE_TYPES.map { it.wireValue },
    activeStatuses,
)

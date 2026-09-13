package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map
import java.time.Instant

/**
 * Live status and target observation for [OutboxRepository].
 * Same-package physical move so the repository class stays under the LargeClass gate.
 */

/**
 * Binding source the live UI streams follow. A reactive [bindingChanges]
 * (AppContainer wires it from the active-ledger settings flow) and the
 * internal revision are invalidation signals only. Every emission re-reads
 * the authoritative binding under [bindingTransitionLease].
 */
private fun OutboxRepository.bindingFlow(): Flow<OutboxBinding> {
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
fun OutboxRepository.observeActiveByTypes(
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
                OutboxRepository.ACTIVE_STATUS_VALUES + PendingMutationStatus.Done.wireValue
            } else {
                OutboxRepository.ACTIVE_STATUS_VALUES
            },
        )
    }.map { rows -> rows.map { it.toDomain() } }
}

@OptIn(ExperimentalCoroutinesApi::class)
fun OutboxRepository.observeStatus(): Flow<OutboxStatus> =
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

suspend fun OutboxRepository.activeForTarget(targetId: String): List<OutboxRow> =
    activeForTarget(currentBinding(), targetId)

/** Only the Debt write owner can turn an unresolved command into a local stop. */
internal suspend fun OutboxRepository.abandonDebtWrite(boundRequest: BoundLedgerRequest, row: OutboxRow): Boolean =
    withActiveBinding(boundRequest) { binding ->
        require(row.type in DEBT_WRITE_TYPES)
        dao.abandonDebtWrite(row.id, binding.ownerStorageKey, binding.ledgerId,
            row.status.wireValue, OutboxRepository.ISO.format(Instant.now(clock))) > 0
    }.also { changed -> if (changed) schedulePending() }

/** Explicit Debt history scope; other mutation types retain their existing observation policy. */
@OptIn(ExperimentalCoroutinesApi::class)
internal fun OutboxRepository.observeDebtWrites(): Flow<List<OutboxRow>> = bindingFlow().flatMapLatest { binding ->
    dao.observeActiveByTypes(
        ownerKey = binding.ownerStorageKey,
        ledgerId = binding.ledgerId,
        types = DEBT_WRITE_TYPES.map { it.wireValue },
        activeStatuses = OutboxRepository.ACTIVE_STATUS_VALUES + listOf(PendingMutationStatus.Done.wireValue,
            PendingMutationStatus.Abandoned.wireValue),
    )
}.map { rows -> rows.map { it.toDomain() } }

internal suspend fun OutboxRepository.activeForTarget(
    boundRequest: BoundLedgerRequest,
    targetId: String,
): List<OutboxRow> = withActiveBinding(boundRequest) { binding ->
    activeForTarget(binding, targetId)
}

internal suspend fun OutboxRepository.activeForTarget(
    binding: OutboxBinding,
    targetId: String,
    statuses: List<String> = OutboxRepository.ACTIVE_STATUS_VALUES,
): List<OutboxRow> = dao.activeForTarget(
    ownerKey = binding.ownerStorageKey,
    ledgerId = binding.ledgerId,
    targetId = targetId,
    activeStatuses = statuses,
).map { it.toDomain() }


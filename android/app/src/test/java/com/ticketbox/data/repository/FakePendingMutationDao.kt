package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationDao
import com.ticketbox.data.local.PendingMutationEntity
import com.ticketbox.data.local.PendingMutationStatus
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.map

/**
 * Pure-Kotlin DAO fake. Mirrors the SQL semantics in the real
 * [PendingMutationDao]; same field names so a future column add
 * shows up as a compile error here too.
 *
 * Shared between [OutboxRepositoryTest] and [OutboxDrainEngineTest]
 * — extracted from the former so the latter can reach it without
 * making the file-private fake public on every test.
 */
class FakePendingMutationDao : PendingMutationDao {
    val rows = linkedMapOf<Long, PendingMutationEntity>()
    var beforeNextRunnableBatchReturn: (suspend () -> Unit)? = null
    private var nextId = 1L
    private val queueDepth = MutableStateFlow(0)
    private val conflictRows = MutableStateFlow<List<PendingMutationEntity>>(emptyList())

    override suspend fun insert(row: PendingMutationEntity): Long {
        val assigned = nextId++
        rows[assigned] = row.copy(id = assigned)
        refreshObservables()
        return assigned
    }

    override suspend fun markInFlightIfPending(
        id: Long,
        fromStatus: String,
        inFlightStatus: String,
        attemptedAt: String,
    ): Int {
        val current = rows[id] ?: return 0
        if (current.status != fromStatus) return 0
        rows[id] = current.copy(
            status = inFlightStatus,
            attemptedAt = attemptedAt,
            retryCount = current.retryCount + 1,
        )
        refreshObservables()
        return 1
    }

    override suspend fun markRetryable(
        id: Long,
        pendingStatus: String,
        lastError: String,
    ): Int {
        val current = rows[id] ?: return 0
        rows[id] = current.copy(status = pendingStatus, lastError = lastError)
        refreshObservables()
        return 1
    }

    override suspend fun markDone(id: Long, status: String, completedAt: String): Int {
        val current = rows[id] ?: return 0
        rows[id] = current.copy(
            status = status,
            completedAt = completedAt,
            lastError = null,
        )
        refreshObservables()
        return 1
    }

    override suspend fun markConflict(id: Long, status: String, lastError: String): Int {
        val current = rows[id] ?: return 0
        rows[id] = current.copy(status = status, lastError = lastError)
        refreshObservables()
        return 1
    }

    override suspend fun markFailed(id: Long, status: String, lastError: String): Int {
        val current = rows[id] ?: return 0
        rows[id] = current.copy(status = status, lastError = lastError)
        refreshObservables()
        return 1
    }

    override suspend fun markExpiredPendingAsFailed(
        cutoffCreatedAtIso: String,
        status: String,
        lastError: String,
    ): Int {
        // Mirrors the DAO SQL: status='pending' AND createdAt < cutoff. createdAt
        // is a fixed-width ISO string so the lexicographic < matches SQLite, same
        // as recoverStaleInFlight's attemptedAt comparison. Global (no binding
        // filter) by design — a stale PENDING row under any binding is a
        // double-apply risk.
        val victims = rows.values.filter {
            it.status == "pending" && it.createdAt < cutoffCreatedAtIso
        }
        for (row in victims) {
            rows[row.id] = row.copy(status = status, lastError = lastError)
        }
        if (victims.isNotEmpty()) refreshObservables()
        return victims.size
    }

    override suspend fun expireBoundRowIfStatusAndOverAge(
        id: Long,
        ownerKey: String,
        ledgerId: String,
        fromStatus: String,
        cutoffCreatedAtIso: String,
    ): Int {
        // Mirrors the DAO SQL: id AND status=fromStatus AND createdAt < cutoff.
        val current = rows[id] ?: return 0
        if (
            current.ownerKey != ownerKey ||
            current.ledgerId != ledgerId ||
            current.status != fromStatus ||
            current.createdAt >= cutoffCreatedAtIso
        ) {
            return 0
        }
        rows[id] = current.copy(status = "failed", lastError = "outbox_row_expired")
        refreshObservables()
        return 1
    }

    override suspend fun refreshToken(
        id: Long,
        pendingStatus: String,
        freshToken: Long,
    ): Int {
        val current = rows[id] ?: return 0
        rows[id] = current.copy(
            status = pendingStatus,
            expectedRowVersion = freshToken,
            lastError = null,
        )
        refreshObservables()
        return 1
    }

    override suspend fun cascadeFreshTokenForTarget(
        ownerKey: String,
        ledgerId: String,
        targetId: String,
        pendingStatus: String,
        freshToken: Long,
    ): Int {
        val matching = rows.values.filter {
            it.ownerKey == ownerKey &&
                it.ledgerId == ledgerId &&
                it.targetId == targetId &&
                it.status == pendingStatus
        }
        for (row in matching) {
            rows[row.id] = row.copy(expectedRowVersion = freshToken)
        }
        if (matching.isNotEmpty()) refreshObservables()
        return matching.size
    }

    override suspend fun nextPendingBatch(
        ownerKey: String,
        ledgerId: String,
        pendingStatus: String,
        limit: Int,
    ): List<PendingMutationEntity> =
        rows.values
            .filter { it.ownerKey == ownerKey && it.ledgerId == ledgerId && it.status == pendingStatus }
            .sortedWith(compareBy({ it.createdAt }, { it.id }))
            .take(limit)

    override suspend fun requeueConflictWithFreshToken(
        id: Long,
        ownerKey: String,
        ledgerId: String,
        freshToken: Long,
        rotatedIdempotencyKey: String?,
    ): Int {
        val current = rows[id] ?: return 0
        if (current.ownerKey != ownerKey || current.ledgerId != ledgerId || current.status != "conflict") return 0
        // codex P1 #7: 同步真实 DAO 的 retryCount = 0 重置, 否则 fake 看不到用户 retry
        // 重置预算的语义。
        rows[id] = current.copy(
            status = "pending",
            expectedRowVersion = freshToken,
            // ADR-0042 §4.8: rotate only key-bearing rows (mirrors the DAO CASE).
            idempotencyKey = if (current.idempotencyKey != null) rotatedIdempotencyKey else null,
            retryCount = 0,
            lastError = null,
        )
        refreshObservables()
        return 1
    }

    override suspend fun requeueFailedWithFreshToken(
        id: Long,
        ownerKey: String,
        ledgerId: String,
        freshToken: Long,
        rotatedIdempotencyKey: String?,
    ): Int {
        val current = rows[id] ?: return 0
        if (current.ownerKey != ownerKey || current.ledgerId != ledgerId || current.status != "failed") return 0
        rows[id] = current.copy(
            status = "pending",
            expectedRowVersion = freshToken,
            idempotencyKey = if (current.idempotencyKey != null) rotatedIdempotencyKey else null,
            retryCount = 0,
            lastError = null,
        )
        refreshObservables()
        return 1
    }

    override suspend fun retryFailed(id: Long, ownerKey: String, ledgerId: String): Int {
        val current = rows[id] ?: return 0
        if (current.ownerKey != ownerKey || current.ledgerId != ledgerId || current.status != "failed") return 0
        rows[id] = current.copy(status = "pending", retryCount = 0, lastError = "manual_retry")
        refreshObservables()
        return 1
    }

    override suspend fun revertClaimWithoutAttempt(
        id: Long,
        pendingStatus: String,
        inFlightStatus: String,
    ): Int {
        // codex P2 #10 follow-up + PR review: 镜像真实 DAO 的 status guard + retryCount
        // 抵消 + attemptedAt 重置 + 保留 lastError(不写)。
        val current = rows[id] ?: return 0
        if (current.status != inFlightStatus) return 0
        rows[id] = current.copy(
            status = pendingStatus,
            retryCount = (current.retryCount - 1).coerceAtLeast(0),
            attemptedAt = null,
        )
        refreshObservables()
        return 1
    }

    override suspend fun deleteIfStatus(
        id: Long,
        ownerKey: String,
        ledgerId: String,
        expectedStatus: String,
    ): Int {
        val current = rows[id] ?: return 0
        if (
            current.ownerKey != ownerKey ||
            current.ledgerId != ledgerId ||
            current.status != expectedStatus
        ) {
            return 0
        }
        rows.remove(id)
        refreshObservables()
        return 1
    }

    override suspend fun nextRunnableBatch(
        ownerKey: String,
        ledgerId: String,
        pendingStatus: String,
        unresolvedStatuses: Collection<String>,
        limit: Int,
    ): List<PendingMutationEntity> {
        val unresolvedTargets = rows.values
            .filter { it.ownerKey == ownerKey && it.ledgerId == ledgerId && it.status in unresolvedStatuses }
            .map { it.targetId }
            .toSet()
        val batch = rows.values
            .filter {
                it.ownerKey == ownerKey &&
                    it.ledgerId == ledgerId &&
                    it.status == pendingStatus &&
                    it.targetId !in unresolvedTargets
            }
            .sortedWith(compareBy({ it.createdAt }, { it.id }))
            .distinctBy { it.targetId }
            .take(limit)
        beforeNextRunnableBatchReturn?.invoke()
        return batch
    }

    override suspend fun isTargetBusy(
        ownerKey: String,
        ledgerId: String,
        targetId: String,
        inFlightStatus: String,
    ): Boolean =
        rows.values.any {
            it.ownerKey == ownerKey &&
                it.ledgerId == ledgerId &&
                it.targetId == targetId &&
                it.status == inFlightStatus
        }

    override suspend fun hasUnresolvedRowForTarget(
        ownerKey: String,
        ledgerId: String,
        targetId: String,
        unresolvedStatuses: Collection<String>,
    ): Boolean {
        return rows.values.any {
            it.ownerKey == ownerKey &&
                it.ledgerId == ledgerId &&
                it.targetId == targetId &&
                it.status in unresolvedStatuses
        }
    }

    override suspend fun recoverStaleInFlight(
        ownerKey: String,
        ledgerId: String,
        staleCutoffIso: String,
        recoveryMessage: String,
    ): Int {
        val victims = rows.values.filter {
            it.ownerKey == ownerKey &&
                it.ledgerId == ledgerId &&
                it.status == PendingMutationStatus.InFlight.wireValue &&
                (it.attemptedAt == null || it.attemptedAt < staleCutoffIso)
        }
        for (row in victims) {
            rows[row.id] = row.copy(status = PendingMutationStatus.Pending.wireValue, lastError = recoveryMessage)
        }
        if (victims.isNotEmpty()) refreshObservables()
        return victims.size
    }

    override suspend fun activeForTarget(
        ownerKey: String,
        ledgerId: String,
        targetId: String,
        activeStatuses: Collection<String>,
    ): List<PendingMutationEntity> {
        return rows.values
            .filter {
                it.ownerKey == ownerKey &&
                    it.ledgerId == ledgerId &&
                    it.targetId == targetId &&
                    it.status in activeStatuses
            }
            .sortedWith(compareBy({ it.createdAt }, { it.id }))
    }

    override fun observeActiveByTypes(
        ownerKey: String,
        ledgerId: String,
        types: Collection<String>,
        activeStatuses: Collection<String>,
    ): Flow<List<PendingMutationEntity>> = queueDepth.map { _ ->
        rows.values
            .filter {
                it.ownerKey == ownerKey &&
                    it.ledgerId == ledgerId &&
                    it.type in types &&
                    it.status in activeStatuses
            }
            .sortedWith(compareBy({ it.createdAt }, { it.id }))
    }

    override fun observeQueueDepth(
        ownerKey: String,
        ledgerId: String,
        pendingStatus: String,
        inFlightStatus: String,
    ): Flow<Int> = queueDepth.map { snapshot ->
        rows.values.count {
            it.ownerKey == ownerKey &&
                it.ledgerId == ledgerId &&
                (it.status == pendingStatus || it.status == inFlightStatus)
        }
            .also { /* read through snapshot to keep StateFlow hot */ snapshot.let { } }
    }

    override fun observeConflictRows(
        ownerKey: String,
        ledgerId: String,
        conflictStatus: String,
    ): Flow<List<PendingMutationEntity>> =
        conflictRows.map { _ ->
            rows.values
                .filter { it.ownerKey == ownerKey && it.ledgerId == ledgerId && it.status == conflictStatus }
                .sortedWith(compareBy({ it.createdAt }, { it.id }))
        }

    override fun observeFailedRows(
        ownerKey: String,
        ledgerId: String,
        failedStatus: String,
    ): Flow<List<PendingMutationEntity>> =
        conflictRows.map { _ ->
            rows.values
                .filter { it.ownerKey == ownerKey && it.ledgerId == ledgerId && it.status == failedStatus }
                .sortedWith(compareBy({ it.createdAt }, { it.id }))
        }

    override suspend fun deleteById(id: Long): Int {
        val existed = rows.remove(id) != null
        refreshObservables()
        return if (existed) 1 else 0
    }

    override suspend fun deleteResolvedBefore(
        doneStatus: String,
        cutoffIso: String,
    ): Int {
        val victims = rows.values.filter {
            it.status == doneStatus &&
                it.completedAt != null &&
                it.completedAt < cutoffIso
        }.map { it.id }
        victims.forEach { rows.remove(it) }
        refreshObservables()
        return victims.size
    }

    override suspend fun clearAll(): Int {
        val removed = rows.size
        rows.clear()
        refreshObservables()
        return removed
    }

    override suspend fun migrateServerUrlAlias(
        ownerKey: String,
        oldServerUrl: String,
        newServerUrl: String,
        ledgerId: String,
    ): Int {
        val aliases = rows.values.filter {
            it.ownerKey == ownerKey && it.serverUrl == oldServerUrl && it.ledgerId == ledgerId
        }
        for (row in aliases) {
            rows[row.id] = row.copy(serverUrl = newServerUrl)
        }
        if (aliases.isNotEmpty()) refreshObservables()
        return aliases.size
    }

    override fun observeQuarantinedCount(activeOwnerKey: String?): Flow<Int> =
        queueDepth.map { snapshot ->
            rows.values.count { activeOwnerKey == null || it.ownerKey == null || it.ownerKey != activeOwnerKey }
                .also { snapshot.let { } }
        }

    override suspend fun deleteQuarantined(activeOwnerKey: String): Int {
        val ids = rows.values
            .filter { it.ownerKey == null || it.ownerKey != activeOwnerKey }
            .map { it.id }
        ids.forEach(rows::remove)
        if (ids.isNotEmpty()) refreshObservables()
        return ids.size
    }

    private fun refreshObservables() {
        queueDepth.value++
        conflictRows.value = conflictRows.value
    }
}

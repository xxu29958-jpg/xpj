package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationDao
import com.ticketbox.data.local.PendingMutationEntity
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

    override suspend fun refreshToken(
        id: Long,
        pendingStatus: String,
        freshToken: String,
    ): Int {
        val current = rows[id] ?: return 0
        rows[id] = current.copy(
            status = pendingStatus,
            expectedUpdatedAt = freshToken,
            lastError = null,
        )
        refreshObservables()
        return 1
    }

    override suspend fun cascadeFreshTokenForTarget(
        targetId: String,
        pendingStatus: String,
        freshToken: String,
    ): Int {
        val matching = rows.values.filter {
            it.targetId == targetId && it.status == pendingStatus
        }
        for (row in matching) {
            rows[row.id] = row.copy(expectedUpdatedAt = freshToken)
        }
        if (matching.isNotEmpty()) refreshObservables()
        return matching.size
    }

    override suspend fun nextPendingBatch(
        pendingStatus: String,
        limit: Int,
    ): List<PendingMutationEntity> =
        rows.values
            .filter { it.status == pendingStatus }
            .sortedWith(compareBy({ it.createdAt }, { it.id }))
            .take(limit)

    override suspend fun isTargetBusy(targetId: String, inFlightStatus: String): Boolean =
        rows.values.any { it.targetId == targetId && it.status == inFlightStatus }

    override suspend fun activeForTarget(
        targetId: String,
        pendingStatus: String,
        inFlightStatus: String,
        conflictStatus: String,
        failedStatus: String,
    ): List<PendingMutationEntity> {
        val active = setOf(pendingStatus, inFlightStatus, conflictStatus, failedStatus)
        return rows.values
            .filter { it.targetId == targetId && it.status in active }
            .sortedWith(compareBy({ it.createdAt }, { it.id }))
    }

    override fun observeQueueDepth(
        pendingStatus: String,
        inFlightStatus: String,
    ): Flow<Int> = queueDepth.map { snapshot ->
        rows.values.count { it.status == pendingStatus || it.status == inFlightStatus }
            .also { /* read through snapshot to keep StateFlow hot */ snapshot.let { } }
    }

    override fun observeConflictRows(conflictStatus: String): Flow<List<PendingMutationEntity>> =
        conflictRows.map { _ ->
            rows.values
                .filter { it.status == conflictStatus }
                .sortedWith(compareBy({ it.createdAt }, { it.id }))
        }

    override suspend fun deleteById(id: Long): Int {
        val existed = rows.remove(id) != null
        refreshObservables()
        return if (existed) 1 else 0
    }

    override suspend fun deleteResolvedBefore(
        doneStatus: String,
        failedStatus: String,
        cutoffIso: String,
    ): Int {
        val terminal = setOf(doneStatus, failedStatus)
        val victims = rows.values.filter {
            it.status in terminal &&
                it.completedAt != null &&
                it.completedAt!! < cutoffIso
        }.map { it.id }
        victims.forEach { rows.remove(it) }
        refreshObservables()
        return victims.size
    }

    private fun refreshObservables() {
        queueDepth.value++
        conflictRows.value = conflictRows.value
    }
}

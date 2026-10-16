package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationDao
import com.ticketbox.data.local.PendingMutationEntity
import com.ticketbox.data.local.PendingMutationStatus
import java.util.Collections
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** Stores original commands and explicit query outcomes; generated Room owns queue eligibility. */
class FakePendingMutationDao : PendingMutationDao {
    val rows: MutableMap<Long, PendingMutationEntity> = Collections.synchronizedMap(linkedMapOf())
    val runnableBatches = ArrayDeque<List<Long>>()
    val batchCalls = mutableListOf<RunnableBatchCall>()
    val tokenCascadeIds = ArrayDeque<List<Long>>()
    val tokenCascadeCalls = mutableListOf<TokenCascadeCall>()
    var beforeNextRunnableBatchReturn: (suspend () -> Unit)? = null
    var beforeInsert: (suspend () -> Unit)? = null
    var replacePayloadError: Throwable? = null
    val refusedClaims = mutableSetOf<Long>()
    val refusedRecoveries = mutableSetOf<Long>()
    val refusedStops = mutableSetOf<Long>()
    val refusedDeletes = mutableSetOf<Long>()
    val deleteCalls = mutableListOf<DeleteCall>()
    // Query outcomes are supplied by the scenario; generated Room owns age/status/binding predicates.
    val expiredPendingIds = mutableListOf<Long>()
    val expiredBoundIds = mutableSetOf<Long>()
    val staleInFlightIds = mutableListOf<Long>()
    var pendingExpiryCutoff: String? = null
        private set
    var boundExpiryCall: BoundExpiryCall? = null
        private set
    var staleRecoveryCall: Triple<String, String, String>? = null
        private set
    private var nextId = 1L
    private val creationAcceptance = Mutex()
    private val queueDepth = MutableStateFlow(0)

    override suspend fun insert(row: PendingMutationEntity): Long {
        beforeInsert?.invoke()
        return insertBatch(listOf(row)).single()
    }

    override suspend fun insertBatch(rows: List<PendingMutationEntity>): List<Long> {
        var next = nextId
        val additions = linkedMapOf<Long, PendingMutationEntity>()
        for (row in rows) {
            val id = if (row.id == 0L) next++ else row.id
            check(id !in this.rows && id !in additions) { "Duplicate outbox primary key" }
            next = maxOf(next, id + 1)
            additions[id] = row.copy(id = id)
        }
        this.rows.putAll(additions)
        nextId = next
        refreshObservables()
        return additions.keys.toList()
    }

    override fun observeOriginalCommand(
        serverUrl: String, ownerKey: String, ledgerId: String, type: String, idempotencyKey: String,
    ): Flow<List<PendingMutationEntity>> = queueDepth.map {
        rows.values.filter { row -> row.serverUrl == serverUrl && row.ownerKey == ownerKey && row.ledgerId == ledgerId &&
            row.type == type && row.idempotencyKey == idempotencyKey }.sortedBy { row -> row.id }
    }

    override fun observeOriginalCommandById(
        serverUrl: String, ownerKey: String, ledgerId: String, type: String, originalId: Long,
    ): Flow<List<PendingMutationEntity>> = queueDepth.map {
        rows.values.filter { row -> row.serverUrl == serverUrl && row.ownerKey == ownerKey && row.ledgerId == ledgerId &&
            row.type == type && row.id == originalId }
    }

    override suspend fun findByIdempotencyKeys(
        ownerKey: String, ledgerId: String, type: String, keys: Collection<String>,
    ): List<PendingMutationEntity> = rows.values
        .filter { it.ownerKey == ownerKey && it.ledgerId == ledgerId && it.type == type && it.idempotencyKey in keys }
        .sortedWith(compareBy({ it.createdAt }, { it.id }))

    override suspend fun insertOriginalCreation(row: PendingMutationEntity): Long = creationAcceptance.withLock {
        super.insertOriginalCreation(row)
    }

    override suspend fun allRows(): List<PendingMutationEntity> = rows.values.sortedWith(compareBy({ it.createdAt }, { it.id }))

    override suspend fun markInFlightIfPending(
        id: Long,
        fromStatus: String,
        inFlightStatus: String,
        attemptedAt: String,
    ): Int {
        val current = rows[id] ?: return 0
        if (refusedClaims.remove(id)) return 0
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

    override suspend fun markDone(id: Long, status: String, completedAt: String, lastError: String?, receiptJson: String?): Int {
        val current = rows[id] ?: return 0
        rows[id] = current.copy(
            status = status,
            completedAt = completedAt,
            lastError = lastError,
            receiptJson = receiptJson,
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

    override suspend fun markFailed(id: Long, status: String, lastError: String, blocksFollowing: Boolean): Int {
        val current = rows[id] ?: return 0
        rows[id] = current.copy(status = status, lastError = lastError, blocksFollowing = blocksFollowing)
        refreshObservables()
        return 1
    }

    override suspend fun markExpiredPendingAsFailed(
        cutoffCreatedAtIso: String,
        status: String,
        lastError: String,
    ): Int {
        pendingExpiryCutoff = cutoffCreatedAtIso
        val victims = expiredPendingIds.toList()
        expiredPendingIds.clear()
        for (id in victims) {
            rows[id] = rows.getValue(id).copy(status = status, lastError = lastError, blocksFollowing = true)
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
        boundExpiryCall = BoundExpiryCall(id, ownerKey, ledgerId, fromStatus, cutoffCreatedAtIso)
        if (!expiredBoundIds.remove(id)) return 0
        rows[id] = rows.getValue(id).copy(status = "failed", lastError = "outbox_row_expired", blocksFollowing = true)
        refreshObservables()
        return 1
    }

    override suspend fun cascadeFreshTokenForTarget(
        ownerKey: String,
        ledgerId: String,
        targetId: String,
        preservedTokenTypes: List<String>,
        freshToken: Long,
    ): Int {
        tokenCascadeCalls += TokenCascadeCall(ownerKey, ledgerId, targetId, preservedTokenTypes, freshToken)
        val ids = tokenCascadeIds.removeFirstOrNull().orEmpty()
        for (id in ids) rows[id] = rows.getValue(id).copy(expectedRowVersion = freshToken)
        if (ids.isNotEmpty()) refreshObservables()
        return ids.size
    }

    override suspend fun requeueConflictWithFreshToken(
        id: Long,
        ownerKey: String,
        ledgerId: String,
        freshToken: Long,
        rotatedIdempotencyKey: String?,
    ): Int {
        val current = rows[id] ?: return 0
        if (id in refusedRecoveries) return 0
        rows[id] = current.copy(
            status = "pending",
            expectedRowVersion = freshToken,
            idempotencyKey = if (current.idempotencyKey != null) rotatedIdempotencyKey else null,
            retryCount = 0,
            lastError = null,
            blocksFollowing = true,
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
        if (id in refusedRecoveries) return 0
        rows[id] = current.copy(
            status = "pending",
            expectedRowVersion = freshToken,
            idempotencyKey = if (current.idempotencyKey != null) rotatedIdempotencyKey else null,
            retryCount = 0,
            lastError = null,
            blocksFollowing = true,
        )
        refreshObservables()
        return 1
    }

    override suspend fun retryFailed(id: Long, ownerKey: String, ledgerId: String, nonRetryableUploadErrors: Set<String>): Int {
        val current = rows[id] ?: return 0
        if (id in refusedRecoveries) return 0
        rows[id] = current.copy(status = "pending", retryCount = 0, lastError = "manual_retry", blocksFollowing = true)
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
        deleteCalls += DeleteCall(id, ownerKey, ledgerId, expectedStatus)
        if (id !in rows || id in refusedDeletes) return 0
        rows.remove(id)
        refreshObservables()
        return 1
    }

    override suspend fun abandonOriginalCommand(
        id: Long,
        ownerKey: String,
        ledgerId: String,
        expectedStatus: String,
        stoppedAt: String,
    ): Int {
        val current = rows[id] ?: return 0
        if (id in refusedStops) return 0
        rows[id] = current.copy(status = "abandoned", completedAt = stoppedAt)
        refreshObservables()
        return 1
    }

    override suspend fun clearExpenseRefresh(id: Long, expectedError: String): Int {
        val current = rows[id] ?: return 0
        if (current.status != "done" || current.lastError != expectedError) return 0
        rows[id] = current.copy(lastError = null)
        refreshObservables()
        return 1
    }

    override suspend fun nextRunnableBatch(
        ownerKey: String,
        ledgerId: String,
        unresolvedStatuses: Collection<String>,
        limit: Int,
        excludedIds: List<Long>,
    ): List<PendingMutationEntity> {
        batchCalls += RunnableBatchCall(ownerKey, ledgerId, unresolvedStatuses.toList(), limit, excludedIds)
        val batch = (runnableBatches.removeFirstOrNull() ?: emptyList()).map(rows::getValue)
        check(batch.all { it.status == "pending" }) { "Scenario offered an original that was not pending" }
        beforeNextRunnableBatchReturn?.invoke()
        return batch
    }

    override suspend fun recoverStaleInFlight(
        ownerKey: String,
        ledgerId: String,
        staleCutoffIso: String,
        recoveryMessage: String,
    ): Int {
        staleRecoveryCall = Triple(ownerKey, ledgerId, staleCutoffIso)
        val victims = staleInFlightIds.toList()
        staleInFlightIds.clear()
        for (id in victims) {
            rows[id] = rows.getValue(id).copy(status = PendingMutationStatus.Pending.wireValue, lastError = recoveryMessage)
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
    ): Flow<List<PendingMutationEntity>> = observeRows().map { snapshot ->
        snapshot
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
    ): Flow<Int> = observeRows().map { snapshot ->
        snapshot.count {
            it.ownerKey == ownerKey &&
                it.ledgerId == ledgerId &&
                (it.status == pendingStatus || it.status == inFlightStatus)
        }
    }

    override fun observeConflictRows(
        ownerKey: String,
        ledgerId: String,
        conflictStatus: String,
    ): Flow<List<PendingMutationEntity>> =
        observeRows().map { snapshot ->
            snapshot
                .filter { it.ownerKey == ownerKey && it.ledgerId == ledgerId && it.status == conflictStatus }
                .sortedWith(compareBy({ it.createdAt }, { it.id }))
        }

    override fun observeFailedRows(
        ownerKey: String,
        ledgerId: String,
        failedStatus: String,
    ): Flow<List<PendingMutationEntity>> =
        observeRows().map { snapshot ->
            snapshot
                .filter { it.ownerKey == ownerKey && it.ledgerId == ledgerId && it.status == failedStatus }
                .sortedWith(compareBy({ it.createdAt }, { it.id }))
        }

    override suspend fun deleteUnfinishedUploadGroup(ownerKey: String, ledgerId: String, targetId: String): Int {
        val ids = rows.values.filter {
            it.ownerKey == ownerKey && it.ledgerId == ledgerId && it.targetId == targetId &&
                it.type == "upload_screenshot" && it.status != "done"
        }.map { it.id }
        ids.forEach(rows::remove)
        if (ids.isNotEmpty()) refreshObservables()
        return ids.size
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
        observeRows().map { snapshot ->
            snapshot.count { activeOwnerKey == null || it.ownerKey == null || it.ownerKey != activeOwnerKey }
        }

    // Real recovery runs on IO while Main observes; publish a stable row set like a Room query.
    private fun observeRows(): Flow<List<PendingMutationEntity>> =
        queueDepth.map { synchronized(rows) { rows.values.toList() } }

    override suspend fun deleteQuarantined(activeOwnerKey: String): Int {
        val ids = rows.values
            .filter { it.ownerKey == null || it.ownerKey != activeOwnerKey }
            .map { it.id }
        ids.forEach(rows::remove)
        if (ids.isNotEmpty()) refreshObservables()
        return ids.size
    }

    override suspend fun replacePayload(id: Long, type: String, payload: String): Int {
        replacePayloadError?.let { throw it }
        val current = rows[id] ?: return 0
        if (current.type != type) return 0
        rows[id] = current.copy(payload = payload)
        refreshObservables()
        return 1
    }

    override suspend fun clearAcceptedReadRefresh(id: Long, receiptJson: String, expectedError: String): Int {
        val current = rows[id] ?: return 0
        if (current.status != "done" || current.lastError != expectedError || current.receiptJson != receiptJson) return 0
        rows[id] = current.copy(lastError = null)
        refreshObservables()
        return 1
    }

    private fun refreshObservables() {
        queueDepth.value++
    }
}

data class BoundExpiryCall(val id: Long, val ownerKey: String, val ledgerId: String, val fromStatus: String, val cutoff: String)

data class RunnableBatchCall(val ownerKey: String, val ledgerId: String, val unresolvedStatuses: List<String>,
    val limit: Int, val excludedIds: List<Long>)

data class TokenCascadeCall(val ownerKey: String, val ledgerId: String, val targetId: String,
    val preservedTypes: List<String>, val freshToken: Long)

data class DeleteCall(val id: Long, val ownerKey: String, val ledgerId: String, val status: String)

package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationDao
import com.ticketbox.data.local.PendingMutationEntity
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.test.runTest
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * ADR-0038 PR-2f contract tests.
 *
 * These exercise the public surface of [OutboxRepository] against a
 * pure-Kotlin in-memory fake of [PendingMutationDao] — no Room
 * dependency in unit tests, so the suite stays fast and JVM-only.
 * The fake mirrors the DAO's SQL semantics field by field; the
 * "real" DAO behaviour gets tested by the instrumented Room test
 * lane CI already runs (``:app:connectedGrayDebugAndroidTest``).
 */
class OutboxRepositoryTest {

    @Test
    fun enqueueInsertsPendingRowInCausalOrder() = runTest {
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))

        val first = repo.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = """{"merchant":"a"}""",
            expectedUpdatedAt = "2026-05-04T00:00:00Z",
        )
        val second = repo.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:2",
            payloadJson = """{"merchant":"b"}""",
            expectedUpdatedAt = "2026-05-04T00:00:00Z",
        )

        val runnable = repo.dequeueNextRunnable(limit = 10)
        assertEquals(listOf(first, second), runnable.map { it.id })
        assertEquals(PendingMutationStatus.Pending.wireValue, dao.rows.values.first().status)
    }

    @Test
    fun dequeueSkipsRowsForTargetsAlreadyInFlight() = runTest {
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))

        val first = repo.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "",
        )
        // Another row for the SAME target — drain must not pick it
        // up while ``first`` is in flight.
        val second = repo.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "",
        )
        // Different target — drain may take it.
        val third = repo.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:2",
            payloadJson = "{}",
            expectedUpdatedAt = "",
        )

        repo.markInFlight(first)
        val runnable = repo.dequeueNextRunnable(limit = 10).map { it.id }

        // ``first`` is IN_FLIGHT so it's no longer PENDING and won't
        // be re-queued; ``second`` shares its target and must wait;
        // ``third`` is independent and runs.
        assertEquals(listOf(third), runnable)
        assertTrue(second !in runnable)
    }

    @Test
    fun markDoneSetsCompletedAt() = runTest {
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", "")

        repo.markDone(id)

        val row = dao.rows[id]!!
        assertEquals(PendingMutationStatus.Done.wireValue, row.status)
        assertNotNull(row.completedAt)
        assertNull(row.lastError)
    }

    @Test
    fun markConflictPreservesServerMessage() = runTest {
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", "")

        repo.markConflict(id, "账单已在其它端被修改，请刷新后重试。")

        val row = dao.rows[id]!!
        assertEquals(PendingMutationStatus.Conflict.wireValue, row.status)
        assertEquals("账单已在其它端被修改，请刷新后重试。", row.lastError)
    }

    @Test
    fun resolveConflictKeepMineRefreshesTokenAndReturnsToPending() = runTest {
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
        val id = repo.enqueue(
            PendingMutationType.PatchExpense,
            "expense:1",
            "{}",
            "2026-05-04T00:00:00Z",
        )
        repo.markConflict(id, "stale")

        repo.resolveConflict(
            id,
            ConflictResolution.KeepMine(freshToken = "2026-05-04T00:01:00Z"),
        )

        val row = dao.rows[id]!!
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        assertEquals("2026-05-04T00:01:00Z", row.expectedUpdatedAt)
        assertNull(row.lastError)
    }

    @Test
    fun resolveConflictDropMineDeletesRow() = runTest {
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", "")
        repo.markConflict(id, "stale")

        repo.resolveConflict(id, ConflictResolution.DropMine)

        assertTrue(dao.rows[id] == null)
    }

    @Test
    fun gcCompletedDeletesTerminalRowsOlderThanRetention() = runTest {
        val dao = FakePendingMutationDao()
        val now = "2026-05-04T12:00:00Z"
        val repo = OutboxRepository(dao = dao, clock = fixedClock(now))

        val oldId = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", "")
        // Hand-edit completedAt to before retention window.
        dao.rows[oldId] = dao.rows[oldId]!!.copy(
            status = PendingMutationStatus.Done.wireValue,
            completedAt = "2026-04-01T00:00:00Z",
        )
        val recentId = repo.enqueue(PendingMutationType.PatchExpense, "expense:2", "{}", "")
        dao.rows[recentId] = dao.rows[recentId]!!.copy(
            status = PendingMutationStatus.Done.wireValue,
            completedAt = now,
        )

        val pruned = repo.gcCompleted()

        assertEquals(1, pruned)
        assertTrue(dao.rows[oldId] == null)
        assertTrue(dao.rows[recentId] != null)
    }

    @Test
    fun activeForTargetExcludesTerminalRows() = runTest {
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))

        val pendingId = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", "")
        val doneId = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", "")
        repo.markDone(doneId)
        repo.enqueue(PendingMutationType.PatchExpense, "expense:2", "{}", "")

        val active = repo.activeForTarget("expense:1").map { it.id }

        assertEquals(listOf(pendingId), active)
    }

    private fun fixedClock(iso: String): Clock =
        Clock.fixed(Instant.parse(iso), ZoneOffset.UTC)
}

/**
 * Pure-Kotlin DAO fake. Mirrors the SQL semantics in the real
 * [PendingMutationDao]; same field names so a future column add
 * shows up as a compile error here too.
 */
private class FakePendingMutationDao : PendingMutationDao {
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

    override suspend fun markInFlight(id: Long, status: String, attemptedAt: String): Int {
        val current = rows[id] ?: return 0
        rows[id] = current.copy(
            status = status,
            attemptedAt = attemptedAt,
            retryCount = current.retryCount + 1,
        )
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

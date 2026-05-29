package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.yield
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

        // Atomic claim flips first PENDING → IN_FLIGHT.
        assertTrue(repo.tryClaim(first))
        val runnable = repo.dequeueNextRunnable(limit = 10).map { it.id }

        // ``first`` is IN_FLIGHT so it's no longer PENDING and won't
        // be re-queued; ``second`` shares its target and must wait;
        // ``third`` is independent and runs.
        assertEquals(listOf(third), runnable)
        assertTrue(second !in runnable)
    }

    @Test
    fun dequeueDedupesSameTargetBeforeApplyingLimit() = runTest {
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))

        val firstSameTarget = repo.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "t0",
        )
        repo.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "t0",
        )
        val differentTarget = repo.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:2",
            payloadJson = "{}",
            expectedUpdatedAt = "t0",
        )

        val runnable = repo.dequeueNextRunnable(limit = 2).map { it.id }

        assertEquals(listOf(firstSameTarget, differentTarget), runnable)
    }

    @Test
    fun markDoneSetsCompletedAt() = runTest {
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", "")

        repo.tryClaim(id)
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
    fun gcCompletedDeletesDoneRowsOlderThanRetention() = runTest {
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
    fun failedRowsAreNotCompletedAndAreNotGarbageCollected() = runTest {
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(
            dao = dao,
            clock = fixedClock("2026-05-04T12:00:00Z"),
        )
        val failedId = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", "")

        repo.markFailed(failedId, "user must decide")
        val pruned = repo.gcCompleted(retentionMillis = 0)

        val row = dao.rows[failedId]
        assertEquals(0, pruned)
        assertNotNull(row)
        assertEquals(PendingMutationStatus.Failed.wireValue, row.status)
        assertNull(row.completedAt)
    }

    @Test
    fun resolveFailedRetryWithoutTokenFlipsBackToPending() = runTest {
        // [codex round-3 P2#2] Without a UI surface, FAILED rows
        // permanently block same-target later mutations because of
        // r2#1's NOT EXISTS filter. ``resolveFailed(Retry)`` must
        // put the row back to PENDING so the next drain re-claims it.
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", "")
        repo.markFailed(id, "transient parse")

        repo.resolveFailed(id, FailedResolution.Retry())

        val row = dao.rows[id]!!
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        // The row's lastError is replaced by the manual-retry
        // marker so the UI knows it was user-initiated.
        assertEquals("manual retry", row.lastError)
    }

    @Test
    fun resolveFailedRetryWithFreshTokenAlsoRefreshesIt() = runTest {
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
        val id = repo.enqueue(
            PendingMutationType.PatchExpense,
            "expense:1",
            "{}",
            "2026-05-04T00:00:00Z",
        )
        repo.markFailed(id, "stale token")

        repo.resolveFailed(id, FailedResolution.Retry(freshToken = "2026-05-04T01:00:00Z"))

        val row = dao.rows[id]!!
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        assertEquals("2026-05-04T01:00:00Z", row.expectedUpdatedAt)
        assertEquals(null, row.lastError)
    }

    @Test
    fun resolveFailedRetryNoOpsIfRowAlreadyDone() = runTest {
        // [codex round-4 P2] A stale banner click after some other
        // surface already retried + DONE this row must NOT flip the
        // DONE row back to PENDING and trigger a duplicate replay.
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", "")
        // Simulate: row was FAILED, another surface retried, drain
        // ran, server accepted → row is now DONE.
        dao.rows[id] = dao.rows[id]!!.copy(
            status = PendingMutationStatus.Done.wireValue,
            completedAt = "2026-05-04T00:01:00Z",
        )

        val changed = repo.resolveFailed(id, FailedResolution.Retry())

        // The retry is a no-op because the row is no longer FAILED.
        assertEquals(false, changed)
        assertEquals(PendingMutationStatus.Done.wireValue, dao.rows[id]!!.status)
    }

    @Test
    fun resolveConflictKeepMineNoOpsIfRowAlreadyPending() = runTest {
        // Mirror of resolveFailedRetryNoOpsIfRowAlreadyDone — if a
        // parallel surface already moved the row out of CONFLICT,
        // a stale banner click is a no-op.
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", "")
        repo.markConflict(id, "stale")
        // Another surface keep-mined first; row is now PENDING.
        dao.rows[id] = dao.rows[id]!!.copy(
            status = PendingMutationStatus.Pending.wireValue,
            expectedUpdatedAt = "fresh-token-from-other-surface",
            lastError = null,
        )

        val changed = repo.resolveConflict(
            id,
            ConflictResolution.KeepMine(freshToken = "stale-banner-token"),
        )

        assertEquals(false, changed)
        // The other surface's fresh token survives.
        assertEquals("fresh-token-from-other-surface", dao.rows[id]!!.expectedUpdatedAt)
    }

    @Test
    fun resolveFailedDropDeletesRow() = runTest {
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", "")
        repo.markFailed(id, "user gave up")

        repo.resolveFailed(id, FailedResolution.Drop)

        assertTrue(dao.rows[id] == null)
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

    @Test
    fun bindingScopedQueueDoesNotDrainRowsFromPreviousLedger() = runTest {
        val dao = FakePendingMutationDao()
        var binding = OutboxBinding("https://old.example.com", "ledger-a")
        val repo = OutboxRepository(
            dao = dao,
            clock = fixedClock("2026-05-04T00:00:00Z"),
            bindingProvider = { binding },
        )

        val oldRow = repo.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "old-token",
        )
        binding = OutboxBinding("https://new.example.com", "ledger-b")
        val newRow = repo.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:2",
            payloadJson = "{}",
            expectedUpdatedAt = "new-token",
        )

        val runnable = repo.dequeueNextRunnable(limit = 10).map { it.id }

        assertEquals(listOf(newRow), runnable)
        assertEquals("https://old.example.com", dao.rows[oldRow]?.serverUrl)
        assertEquals("ledger-a", dao.rows[oldRow]?.ledgerId)
    }

    @Test
    fun observeStatusAggregatesCurrentBindingOnly() = runTest {
        val dao = FakePendingMutationDao()
        var binding = OutboxBinding("https://api.example.com", "active")
        val repo = OutboxRepository(
            dao = dao,
            clock = fixedClock("2026-05-04T00:00:00Z"),
            bindingProvider = { binding },
        )
        val activePending = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", "")
        val activeConflict = repo.enqueue(PendingMutationType.PatchExpense, "expense:2", "{}", "")
        repo.markConflict(activeConflict, "stale")

        binding = OutboxBinding("https://api.example.com", "other")
        repo.enqueue(PendingMutationType.PatchExpense, "expense:3", "{}", "")
        binding = OutboxBinding("https://api.example.com", "active")

        val status = repo.observeStatus().first()

        assertEquals(1, status.queueDepth)
        assertEquals(listOf(activeConflict), status.conflicts.map { it.id })
        assertTrue(status.needsUserAction)
        assertEquals("active", dao.rows[activePending]?.ledgerId)
    }

    @Test
    fun recoverStaleInFlightScopesToCurrentBindingOnly() = runTest {
        val dao = FakePendingMutationDao()
        var binding = OutboxBinding("https://api.example.com", "active")
        val repo = OutboxRepository(
            dao = dao,
            clock = fixedClock("2026-05-04T00:00:00Z"),
            bindingProvider = { binding },
        )
        val activeRow = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", "")
        dao.rows[activeRow] = dao.rows[activeRow]!!.copy(
            status = PendingMutationStatus.InFlight.wireValue,
            attemptedAt = "2026-05-03T00:00:00.000Z",
        )

        binding = OutboxBinding("https://api.example.com", "other")
        val otherRow = repo.enqueue(PendingMutationType.PatchExpense, "expense:2", "{}", "")
        dao.rows[otherRow] = dao.rows[otherRow]!!.copy(
            status = PendingMutationStatus.InFlight.wireValue,
            attemptedAt = "2026-05-03T00:00:00.000Z",
        )

        binding = OutboxBinding("https://api.example.com", "active")
        val recovered = repo.recoverStaleInFlight()

        assertEquals(1, recovered)
        assertEquals(PendingMutationStatus.Pending.wireValue, dao.rows[activeRow]?.status)
        assertEquals(PendingMutationStatus.InFlight.wireValue, dao.rows[otherRow]?.status)
    }

    @Test
    fun enqueueWaitsForBindingTransitionAndCannotPersistMixedBinding() = runTest {
        val dao = FakePendingMutationDao()
        var binding = OutboxBinding("https://old.example.com", "ledger-a")
        val repo = OutboxRepository(
            dao = dao,
            clock = fixedClock("2026-05-04T00:00:00Z"),
            bindingProvider = { binding },
        )
        val transitionStarted = CompletableDeferred<Unit>()
        val releaseTransition = CompletableDeferred<Unit>()

        val transition = async {
            repo.withBindingTransition {
                binding = OutboxBinding("https://new.example.com", "ledger-a")
                transitionStarted.complete(Unit)
                releaseTransition.await()
                binding = OutboxBinding("https://new.example.com", "ledger-b")
            }
        }
        transitionStarted.await()

        val enqueue = async {
            repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", "token")
        }
        yield()
        assertEquals(0, dao.rows.size)

        releaseTransition.complete(Unit)
        val rowId = enqueue.await()
        transition.await()

        val row = dao.rows[rowId]!!
        assertEquals("https://new.example.com", row.serverUrl)
        assertEquals("ledger-b", row.ledgerId)
    }

    private fun fixedClock(iso: String): Clock =
        Clock.fixed(Instant.parse(iso), ZoneOffset.UTC)
}

// FakePendingMutationDao moved to its own file so OutboxDrainEngineTest
// can reuse it without a file-private declaration.

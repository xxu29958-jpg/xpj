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
import kotlin.test.assertNotEquals
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
            expectedRowVersion = 1L,
        )
        val second = repo.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:2",
            payloadJson = """{"merchant":"b"}""",
            expectedRowVersion = 1L,
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
            expectedRowVersion = 0L,
        )
        // Another row for the SAME target — drain must not pick it
        // up while ``first`` is in flight.
        val second = repo.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedRowVersion = 0L,
        )
        // Different target — drain may take it.
        val third = repo.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:2",
            payloadJson = "{}",
            expectedRowVersion = 0L,
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
            expectedRowVersion = 1L,
        )
        repo.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedRowVersion = 1L,
        )
        val differentTarget = repo.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:2",
            payloadJson = "{}",
            expectedRowVersion = 1L,
        )

        val runnable = repo.dequeueNextRunnable(limit = 2).map { it.id }

        assertEquals(listOf(firstSameTarget, differentTarget), runnable)
    }

    @Test
    fun markDoneSetsCompletedAt() = runTest {
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 0L)

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
        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 0L)

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
            1L,
        )
        // PR review #6: 预设 retryCount=5 制造"用户在 5 次失败后才看到 conflict"的真场景,
        // 然后断言 KeepMine 把它重置为 0(用户显式重试,该拿到完整 max_attempts 预算)。
        dao.rows[id] = dao.rows[id]!!.copy(retryCount = 5)
        repo.markConflict(id, "stale")

        repo.resolveConflict(
            id,
            ConflictResolution.KeepMine(freshToken = 2L),
        )

        val row = dao.rows[id]!!
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        assertEquals(2L, row.expectedRowVersion)
        assertNull(row.lastError)
        assertEquals(0, row.retryCount, "KeepMine 是用户显式重试, 必须重置 retryCount 给 max_attempts 完整预算")
    }

    @Test
    fun resolveConflictKeepMineRotatesIdempotencyKeyForKeyBearingRow() = runTest {
        // ADR-0042 §4.8: KeepMine refreshes the token = "overwrite the new server
        // version after seeing the conflict" NEW intent, so a key-bearing row
        // (PatchExpense) must ROTATE its idempotency key — otherwise the replay's
        // fingerprint (which folds in the token) would mismatch the original key.
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
        val id = repo.enqueue(
            PendingMutationType.PatchExpense,
            "expense:1",
            "{}",
            1L,
            idempotencyKey = "key-original",
        )
        repo.markConflict(id, "stale")

        repo.resolveConflict(id, ConflictResolution.KeepMine(freshToken = 2L))

        val rotated = dao.rows[id]!!.idempotencyKey
        assertNotNull(rotated, "KeepMine must keep a key-bearing row keyed")
        assertNotEquals("key-original", rotated, "KeepMine must ROTATE the key, not reuse it")
    }

    @Test
    fun resolveConflictKeepMineLeavesKeylessRowNull() = runTest {
        // A keyless mutation type (confirm/reject etc. — no idempotency key in
        // Slice B) must NOT gain a key on KeepMine; the DAO CASE only rotates
        // rows that already carry one.
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
        val id = repo.enqueue(PendingMutationType.ConfirmExpense, "expense:1", "{}", 1L)
        repo.markConflict(id, "stale")

        repo.resolveConflict(id, ConflictResolution.KeepMine(freshToken = 2L))

        assertNull(dao.rows[id]!!.idempotencyKey, "keyless row must stay keyless after KeepMine")
    }

    @Test
    fun resolveConflictDropMineDeletesRow() = runTest {
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 0L)
        repo.markConflict(id, "stale")

        repo.resolveConflict(id, ConflictResolution.DropMine)

        assertTrue(dao.rows[id] == null)
    }

    @Test
    fun gcCompletedDeletesDoneRowsOlderThanRetention() = runTest {
        val dao = FakePendingMutationDao()
        val now = "2026-05-04T12:00:00Z"
        val repo = OutboxRepository(dao = dao, clock = fixedClock(now))

        val oldId = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 0L)
        // Hand-edit completedAt to before retention window.
        dao.rows[oldId] = dao.rows[oldId]!!.copy(
            status = PendingMutationStatus.Done.wireValue,
            completedAt = "2026-04-01T00:00:00Z",
        )
        val recentId = repo.enqueue(PendingMutationType.PatchExpense, "expense:2", "{}", 0L)
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
    fun reapExpiredPendingFailsOverAgeRowAndLeavesFreshRowUntouched() = runTest {
        // ADR-0042 §4.10: a row that has sat PENDING past the age-cap can no
        // longer trust its idempotency key (server retention ~30d > 7d cap), so it
        // must be reaped — flipped to FAILED with the outbox_row_expired marker,
        // NEVER replayed. A fresh PENDING row (well within the cap) is untouched.
        val dao = FakePendingMutationDao()
        val now = "2026-05-04T12:00:00Z"
        val repo = OutboxRepository(dao = dao, clock = fixedClock(now))

        val staleId = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)
        // Hand-edit createdAt to a month ago — far past the 7-day cap.
        dao.rows[staleId] = dao.rows[staleId]!!.copy(createdAt = "2026-04-01T00:00:00.000Z")
        // A fresh row enqueued at the fixed clock (createdAt = now) is inside the cap.
        val freshId = repo.enqueue(PendingMutationType.PatchExpense, "expense:2", "{}", 1L)

        val nowMillis = Instant.parse(now).toEpochMilli()
        val reaped = repo.reapExpiredPending(nowMillis)

        assertEquals(1, reaped, "exactly the over-age PENDING row is reaped")
        val stale = dao.rows[staleId]!!
        assertEquals(PendingMutationStatus.Failed.wireValue, stale.status)
        assertEquals("outbox_row_expired", stale.lastError)
        val fresh = dao.rows[freshId]!!
        assertEquals(PendingMutationStatus.Pending.wireValue, fresh.status, "fresh row stays PENDING")
        assertNull(fresh.lastError)
    }

    @Test
    fun reapExpiredPendingIgnoresNonPendingRowsEvenWhenOverAge() = runTest {
        // The DAO guard is status='pending' only: an over-age CONFLICT / FAILED /
        // IN_FLIGHT row is awaiting the user or mid-send and must NOT be re-stamped
        // by the reaper. Confirms the reap is scoped to un-dispatched rows.
        val dao = FakePendingMutationDao()
        val now = "2026-05-04T12:00:00Z"
        val repo = OutboxRepository(dao = dao, clock = fixedClock(now))

        val conflictId = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)
        repo.markConflict(conflictId, "stale")
        dao.rows[conflictId] = dao.rows[conflictId]!!.copy(createdAt = "2026-04-01T00:00:00.000Z")

        val reaped = repo.reapExpiredPending(Instant.parse(now).toEpochMilli())

        assertEquals(0, reaped)
        val row = dao.rows[conflictId]!!
        assertEquals(PendingMutationStatus.Conflict.wireValue, row.status, "over-age CONFLICT is not reaped")
        assertEquals("stale", row.lastError)
    }

    @Test
    fun resolveFailedRetryExpiresOverAgeRowInsteadOfRequeuing() = runTest {
        // ADR-0042 §4.10: the reaper skips non-PENDING rows, so an old FAILED row
        // (max_attempts_exceeded) never carries outbox_row_expired. Retrying it would
        // flip it to PENDING with its original createdAt → the next drain instantly
        // re-reaps it (dead action + double-apply risk). resolveFailed must expire it.
        val dao = FakePendingMutationDao()
        val now = "2026-05-04T12:00:00Z"
        val repo = OutboxRepository(dao = dao, clock = fixedClock(now))

        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)
        repo.markFailed(id, "max_attempts_exceeded(10/10): server 503")
        dao.rows[id] = dao.rows[id]!!.copy(createdAt = "2026-04-01T00:00:00.000Z")

        val changed = repo.resolveFailed(id, FailedResolution.Retry())

        assertTrue(changed, "resolving an over-age FAILED row changes it (to expired)")
        val row = dao.rows[id]!!
        assertEquals(PendingMutationStatus.Failed.wireValue, row.status, "stays terminal, not re-queued")
        assertEquals("outbox_row_expired", row.lastError)
    }

    @Test
    fun resolveConflictKeepMineExpiresOverAgeRowInsteadOfRequeuing() = runTest {
        // Same age guard on the keep-mine path — a rotated key can't undo a
        // committed-but-unseen original whose server key the retention purged.
        val dao = FakePendingMutationDao()
        val now = "2026-05-04T12:00:00Z"
        val repo = OutboxRepository(dao = dao, clock = fixedClock(now))

        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)
        repo.markConflict(id, "stale token")
        dao.rows[id] = dao.rows[id]!!.copy(createdAt = "2026-04-01T00:00:00.000Z")

        val changed = repo.resolveConflict(id, ConflictResolution.KeepMine(freshToken = 9L))

        assertTrue(changed)
        val row = dao.rows[id]!!
        assertEquals(PendingMutationStatus.Failed.wireValue, row.status, "expired, not re-queued to PENDING")
        assertEquals("outbox_row_expired", row.lastError)
    }

    @Test
    fun resolveFailedRetryOnFreshRowRequeuesNormally() = runTest {
        // Control: a FAILED row inside the cap retries normally (flip to PENDING).
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T12:00:00Z"))

        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)
        repo.markFailed(id, "transient parse")

        val changed = repo.resolveFailed(id, FailedResolution.Retry())

        assertTrue(changed)
        val row = dao.rows[id]!!
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status, "fresh row retries to PENDING")
        assertEquals("manual_retry", row.lastError)
    }

    @Test
    fun failedRowsAreNotCompletedAndAreNotGarbageCollected() = runTest {
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(
            dao = dao,
            clock = fixedClock("2026-05-04T12:00:00Z"),
        )
        val failedId = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 0L)

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
        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 0L)
        repo.markFailed(id, "transient parse")

        repo.resolveFailed(id, FailedResolution.Retry())

        val row = dao.rows[id]!!
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        // The row's lastError is replaced by the manual_retry marker so the UI knows it
        // was user-initiated. snake_case 与 ``recovered_from_stuck_in_flight`` /
        // ``no_dispatcher_registered:`` / ``session_boundary_aborted`` 等项目内已有
        // marker 对齐(原 PR review P3 style)。
        assertEquals("manual_retry", row.lastError)
    }

    @Test
    fun resolveFailedRetryWithFreshTokenAlsoRefreshesIt() = runTest {
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
        val id = repo.enqueue(
            PendingMutationType.PatchExpense,
            "expense:1",
            "{}",
            1L,
        )
        // PR review #13: 预设 retryCount=7 制造"用户在 7 次失败 + max_attempts FAILED 后,
        // 用 freshToken 重试"的真场景。断言 retryCount 重置 0(用户拿 fresh token 显式重试,
        // 该重新获得完整预算, 否则再两次 RetryableFailure 又撞 cap)。
        dao.rows[id] = dao.rows[id]!!.copy(retryCount = 7)
        repo.markFailed(id, "stale token")

        repo.resolveFailed(id, FailedResolution.Retry(freshToken = 2L))

        val row = dao.rows[id]!!
        assertEquals(PendingMutationStatus.Pending.wireValue, row.status)
        assertEquals(2L, row.expectedRowVersion)
        assertEquals(null, row.lastError)
        assertEquals(0, row.retryCount, "Retry(freshToken) 也是用户显式重试, 必须重置 retryCount")
    }

    @Test
    fun resolveFailedRetryNoOpsIfRowAlreadyDone() = runTest {
        // [codex round-4 P2] A stale banner click after some other
        // surface already retried + DONE this row must NOT flip the
        // DONE row back to PENDING and trigger a duplicate replay.
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 0L)
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
        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 0L)
        repo.markConflict(id, "stale")
        // Another surface keep-mined first; row is now PENDING.
        dao.rows[id] = dao.rows[id]!!.copy(
            status = PendingMutationStatus.Pending.wireValue,
            expectedRowVersion = 7L,
            lastError = null,
        )

        val changed = repo.resolveConflict(
            id,
            ConflictResolution.KeepMine(freshToken = 9L),
        )

        assertEquals(false, changed)
        // The other surface's fresh token survives.
        assertEquals(7L, dao.rows[id]!!.expectedRowVersion)
    }

    @Test
    fun resolveFailedDropDeletesRow() = runTest {
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 0L)
        repo.markFailed(id, "user gave up")

        repo.resolveFailed(id, FailedResolution.Drop)

        assertTrue(dao.rows[id] == null)
    }

    @Test
    fun activeForTargetExcludesTerminalRows() = runTest {
        val dao = FakePendingMutationDao()
        val repo = OutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))

        val pendingId = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 0L)
        val doneId = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 0L)
        repo.markDone(doneId)
        repo.enqueue(PendingMutationType.PatchExpense, "expense:2", "{}", 0L)

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
            expectedRowVersion = 1L,
        )
        binding = OutboxBinding("https://new.example.com", "ledger-b")
        val newRow = repo.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:2",
            payloadJson = "{}",
            expectedRowVersion = 2L,
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
        val activePending = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 0L)
        val activeConflict = repo.enqueue(PendingMutationType.PatchExpense, "expense:2", "{}", 0L)
        repo.markConflict(activeConflict, "stale")

        binding = OutboxBinding("https://api.example.com", "other")
        repo.enqueue(PendingMutationType.PatchExpense, "expense:3", "{}", 0L)
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
        val activeRow = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 0L)
        dao.rows[activeRow] = dao.rows[activeRow]!!.copy(
            status = PendingMutationStatus.InFlight.wireValue,
            attemptedAt = "2026-05-03T00:00:00.000Z",
        )

        binding = OutboxBinding("https://api.example.com", "other")
        val otherRow = repo.enqueue(PendingMutationType.PatchExpense, "expense:2", "{}", 0L)
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
            repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)
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

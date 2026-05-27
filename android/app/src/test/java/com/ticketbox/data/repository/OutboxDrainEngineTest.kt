package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * ADR-0038 PR-2g drain engine contract.
 *
 * Exercises the pure-Kotlin orchestrator with a fake dispatcher per
 * outcome. The actual ApiService → Retrofit → HttpException path
 * stays in instrumented tests because the failure mapping there is
 * Retrofit-version-specific.
 */
class OutboxDrainEngineTest {

    @Test
    fun successfulDispatchMarksRowDone() = runTest {
        val (engine, outbox) = withDispatcher(StubDispatcher(result = DispatchResult.Success()))
        val rowId = outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "2026-05-04T00:00:00Z",
        )

        val summary = engine.drainOnce()

        assertEquals(1, summary.attempted)
        assertEquals(1, summary.done)
        assertTrue(outbox.activeForTarget("expense:1").isEmpty())
    }

    @Test
    fun conflictDispatchPutsRowInConflict() = runTest {
        val (engine, outbox) = withDispatcher(
            StubDispatcher(result = DispatchResult.Conflict("账单已在其它端被修改")),
        )
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "2026-05-04T00:00:00Z",
        )

        val summary = engine.drainOnce()

        assertEquals(1, summary.conflicts)
        val rows = outbox.activeForTarget("expense:1")
        assertEquals(1, rows.size)
        assertEquals(PendingMutationStatus.Conflict, rows.single().status)
        assertEquals("账单已在其它端被修改", rows.single().lastError)
    }

    @Test
    fun failureDispatchMarksRowFailed() = runTest {
        val (engine, outbox) = withDispatcher(
            StubDispatcher(result = DispatchResult.Failure("network blip")),
        )
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "2026-05-04T00:00:00Z",
        )

        val summary = engine.drainOnce()

        assertEquals(1, summary.failures)
        val row = outbox.activeForTarget("expense:1").single()
        assertEquals(PendingMutationStatus.Failed, row.status)
        assertEquals("network blip", row.lastError)
    }

    @Test
    fun discardedDispatchMarksRowDoneSilently() = runTest {
        // ADR-0038 contract: 404 / non-conflict 409 → discard, no
        // user-facing banner. The drain engine surfaces this as
        // markDone so cleanup garbage-collects the row.
        val (engine, outbox) = withDispatcher(
            StubDispatcher(result = DispatchResult.Discarded("已不存在")),
        )
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "2026-05-04T00:00:00Z",
        )

        val summary = engine.drainOnce()

        assertEquals(1, summary.discarded)
        assertTrue(outbox.activeForTarget("expense:1").isEmpty())
    }

    @Test
    fun dispatcherThrowingMapsToRetryableFailure() = runTest {
        // [codex P1#3] An uncaught throw is treated as transient —
        // the row goes back to PENDING with the error recorded so
        // the next drain tick can try again. A real coding bug
        // will keep failing and eventually surface via retryCount,
        // but a one-off OOM / cancellation shouldn't kick the row
        // out of auto-replay.
        val (engine, outbox) = withDispatcher(
            StubDispatcher(throwError = IllegalStateException("kaboom")),
        )
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "",
        )

        val summary = engine.drainOnce()

        assertEquals(1, summary.retryable)
        val row = outbox.activeForTarget("expense:1").single()
        assertEquals(PendingMutationStatus.Pending, row.status)
        assertEquals("kaboom", row.lastError)
        assertEquals(1, row.retryCount)
    }

    @Test
    fun rowsWithNoRegisteredDispatcherMarkedFailed() = runTest {
        // [codex P2#5] Without a registered dispatcher the row used
        // to stay PENDING and block newer same-or-later rows behind
        // it. New behaviour: mark FAILED with a structured
        // ``lastError`` so the row leaves the PENDING queue and
        // the UI can offer "upgrade and retry" or "drop".
        val (engine, outbox) = withDispatcher(StubDispatcher(result = DispatchResult.Success()))
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "",
        )
        outbox.enqueue(
            type = PendingMutationType.ConfirmExpense,
            targetId = "expense:99",
            payloadJson = "{}",
            expectedUpdatedAt = "",
        )

        val summary = engine.drainOnce()

        assertEquals(2, summary.attempted)
        assertEquals(1, summary.done)
        assertEquals(1, summary.unsupported)
        val unsupportedRow = outbox.activeForTarget("expense:99").single()
        assertEquals(PendingMutationStatus.Failed, unsupportedRow.status)
        assertEquals("no_dispatcher_registered:confirm_expense", unsupportedRow.lastError)
    }

    @Test
    fun retryableFailureKeepsRowPendingForNextDrain() = runTest {
        // [codex P1#3] 5xx / network blip → PENDING, picked up
        // again on the next drainOnce() call.
        val (engine, outbox) = withDispatcher(
            StubDispatcher(result = DispatchResult.RetryableFailure("server 503")),
        )
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "",
        )

        val first = engine.drainOnce()
        assertEquals(1, first.retryable)
        val between = outbox.activeForTarget("expense:1").single()
        assertEquals(PendingMutationStatus.Pending, between.status)
        assertEquals(1, between.retryCount)
        assertEquals("server 503", between.lastError)

        val second = engine.drainOnce()
        assertEquals(1, second.attempted)
        assertEquals(1, second.retryable)
        assertEquals(2, outbox.activeForTarget("expense:1").single().retryCount)
    }

    @Test
    fun successCascadesNewTokenToSameTargetPendingRows() = runTest {
        // [codex P1#1] Offline chain A → B against the same target.
        // After A lands, the server moves to T1; B's row must be
        // rewritten to T1 so it doesn't fake-conflict.
        val (engine, outbox) = withDispatcher(
            StubDispatcher(result = DispatchResult.Success(newUpdatedAt = "2026-05-04T01:00:00Z")),
        )
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "2026-05-04T00:00:00Z",
        )
        val secondId = outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "2026-05-04T00:00:00Z",
        )

        val summary = engine.drainOnce()

        // Same-target dedup means only first runs this pass.
        assertEquals(1, summary.attempted)
        assertEquals(1, summary.done)

        val second = outbox.activeForTarget("expense:1").single { it.id == secondId }
        assertEquals(PendingMutationStatus.Pending, second.status)
        assertEquals("2026-05-04T01:00:00Z", second.expectedUpdatedAt)
    }

    @Test
    fun sameTargetSerialInsideOneDrain() = runTest {
        // [codex P1#1] Two PENDING rows for the same target → only
        // the oldest comes out of this drain batch; the second
        // waits for the next tick.
        val (engine, outbox) = withDispatcher(StubDispatcher(result = DispatchResult.Success()))
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "2026-05-04T00:00:00Z",
        )
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "2026-05-04T00:00:00Z",
        )

        val summary = engine.drainOnce()
        assertEquals(1, summary.attempted)
        assertEquals(1, summary.done)
        assertEquals(
            PendingMutationStatus.Pending,
            outbox.activeForTarget("expense:1").single().status,
        )
    }

    @Test
    fun preClaimedRowIsExcludedFromDispatch() = runTest {
        // [codex P1#2] Atomic claim. Simulate "another drain already
        // grabbed this row" by claiming it before drainOnce reads
        // the batch. The dispatcher must NOT be called.
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        var calls = 0
        val dispatcher = object : OutboxMutationDispatcher {
            override val type = PendingMutationType.PatchExpense
            override suspend fun dispatch(row: OutboxRow): DispatchResult {
                calls++
                return DispatchResult.Success()
            }
        }
        val engine = OutboxDrainEngine(outbox, listOf(dispatcher))
        val id = outbox.enqueue(
            PendingMutationType.PatchExpense,
            "expense:1",
            "{}",
            "",
        )
        // Pre-claim before drainOnce runs.
        outbox.tryClaim(id)

        val summary = engine.drainOnce()

        assertEquals(0, calls, "dispatcher must not run on a pre-claimed row")
        // Dequeue filter "skip rows whose target is IN_FLIGHT"
        // keeps the row out entirely.
        assertEquals(0, summary.attempted)
    }

    private fun withDispatcher(
        dispatcher: OutboxMutationDispatcher,
    ): Pair<OutboxDrainEngine, OutboxRepository> {
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val engine = OutboxDrainEngine(outbox, listOf(dispatcher))
        return engine to outbox
    }
}

private class StubDispatcher(
    private val result: DispatchResult? = null,
    private val throwError: Throwable? = null,
) : OutboxMutationDispatcher {
    override val type: PendingMutationType = PendingMutationType.PatchExpense

    override suspend fun dispatch(row: OutboxRow): DispatchResult {
        throwError?.let { throw it }
        return result ?: DispatchResult.Success()
    }
}

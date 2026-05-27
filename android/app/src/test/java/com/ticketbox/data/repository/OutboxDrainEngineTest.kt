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
        val (engine, outbox) = withDispatcher(StubDispatcher(result = DispatchResult.Success))
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
    fun dispatcherThrowingMapsToFailure() = runTest {
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

        assertEquals(1, summary.failures)
        assertEquals(
            "kaboom",
            outbox.activeForTarget("expense:1").single().lastError,
        )
    }

    @Test
    fun rowsWithNoRegisteredDispatcherAreSkipped() = runTest {
        // Engine only knows how to handle PatchExpense; a queued
        // ConfirmExpense has no dispatcher registered yet (it's
        // landing in a follow-up PR). The engine must leave such
        // rows alone — neither mark them done nor failed.
        val (engine, outbox) = withDispatcher(StubDispatcher(result = DispatchResult.Success))
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
        assertEquals(1, summary.skipped)
        // ConfirmExpense row stays around for a future PR's dispatcher
        // to pick up.
        val pending = outbox.activeForTarget("expense:99").single()
        assertEquals(PendingMutationStatus.Pending, pending.status)
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
        return result ?: DispatchResult.Success
    }
}

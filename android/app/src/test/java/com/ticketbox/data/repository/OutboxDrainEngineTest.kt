package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.yield
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
    fun blockedTargetsDoNotStarveOtherRunnableTargets() = runTest {
        // [codex round-3 P2#1] If the first N PENDING rows in
        // createdAt order all target a CONFLICT-blocked row, the
        // SQL filter must exclude them BEFORE LIMIT — otherwise
        // a runnable row for a different target waiting behind
        // them never enters the drain batch.
        val (engine, outbox) = withDispatcher(StubDispatcher(result = DispatchResult.Success()))
        val blockedHead = outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "",
        )
        outbox.markConflict(blockedHead, "stale")
        // 30 PENDING rows for the blocked target — under the old
        // Kotlin-side filter these would have eaten the whole
        // LIMIT before the runnable row was reached.
        repeat(30) {
            outbox.enqueue(
                type = PendingMutationType.PatchExpense,
                targetId = "expense:1",
                payloadJson = "{}",
                expectedUpdatedAt = "",
            )
        }
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:2",
            payloadJson = "{}",
            expectedUpdatedAt = "",
        )

        val summary = engine.drainOnce()
        // expense:2 runs; the 30 expense:1 PENDING rows wait
        // behind the CONFLICT head.
        assertEquals(1, summary.attempted)
        assertEquals(1, summary.done)
    }

    @Test
    fun conflictSiblingBlocksLaterPendingRow() = runTest {
        // [codex round-2 P1#1] An unresolved CONFLICT for the same
        // target must hold back later PENDING siblings — otherwise
        // the user's keep/drop decision races with the auto-replay
        // of B and the eventual state is non-deterministic.
        val (engine, outbox) = withDispatcher(StubDispatcher(result = DispatchResult.Success()))
        val firstId = outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "",
        )
        outbox.markConflict(firstId, "stale")
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "",
        )

        val summary = engine.drainOnce()
        assertEquals(0, summary.attempted)
        // CONFLICT row unchanged; PENDING sibling untouched.
        val rows = outbox.activeForTarget("expense:1")
        assertEquals(2, rows.size)
        assertTrue(rows.any { it.status == PendingMutationStatus.Conflict })
        assertTrue(rows.any { it.status == PendingMutationStatus.Pending })
    }

    @Test
    fun failedSiblingBlocksLaterPendingRow() = runTest {
        // [codex round-2 P1#1] Same logic for FAILED — user might
        // manually retry or dismiss; until they do, later siblings
        // must wait so the chain order is preserved.
        val (engine, outbox) = withDispatcher(StubDispatcher(result = DispatchResult.Success()))
        val firstId = outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "",
        )
        outbox.markFailed(firstId, "bad payload")
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedUpdatedAt = "",
        )

        val summary = engine.drainOnce()
        assertEquals(0, summary.attempted)
        val rows = outbox.activeForTarget("expense:1")
        assertTrue(rows.any { it.status == PendingMutationStatus.Failed })
        assertTrue(rows.any { it.status == PendingMutationStatus.Pending })
    }

    @Test
    fun cancellationDuringDispatchRollsRowBackToPending() = runTest {
        // [codex round-2 P1#2] CancellationException must propagate
        // to the caller (WorkManager), and the row must be put back
        // to PENDING so the next drain after the worker restarts
        // re-claims it instead of leaving it stuck IN_FLIGHT.
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val dispatcher = object : OutboxMutationDispatcher {
            override val type = PendingMutationType.PatchExpense
            override suspend fun dispatch(row: OutboxRow): DispatchResult {
                throw kotlinx.coroutines.CancellationException("worker cancelled")
            }
        }
        val engine = OutboxDrainEngine(outbox, listOf(dispatcher))
        outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", "")

        val thrown = runCatching { engine.drainOnce() }.exceptionOrNull()
        assertTrue(
            thrown is kotlinx.coroutines.CancellationException,
            "CancellationException must propagate, got $thrown",
        )

        val row = outbox.activeForTarget("expense:1").single()
        assertEquals(PendingMutationStatus.Pending, row.status)
        assertEquals("drain cancelled mid-dispatch", row.lastError)
    }

    @Test
    fun staleInFlightSweptBackToPendingAtDrainStart() = runTest {
        // [codex round-2 P1#2 companion] A row left IN_FLIGHT by a
        // dead worker would permanently block same-target siblings
        // via the unresolved-row dedup. The drain engine sweeps
        // IN_FLIGHT rows whose attemptedAt is older than the stale
        // threshold back to PENDING before dequeueing.
        val dao = FakePendingMutationDao()
        val now = java.time.Instant.parse("2026-05-04T12:00:00Z")
        val outbox = OutboxRepository(
            dao = dao,
            clock = java.time.Clock.fixed(now, java.time.ZoneOffset.UTC),
        )
        // Direct-poke a row into IN_FLIGHT with attemptedAt ten
        // minutes ago (older than the 5-minute stale threshold).
        val id = outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", "")
        dao.rows[id] = dao.rows[id]!!.copy(
            status = PendingMutationStatus.InFlight.wireValue,
            attemptedAt = "2026-05-04T11:50:00Z",
        )

        val engine = OutboxDrainEngine(
            outbox,
            listOf(StubDispatcher(result = DispatchResult.Success())),
        )
        val summary = engine.drainOnce()

        // The sweep flips it back to PENDING; the same drainOnce
        // pass then dequeues, claims, and dispatches it → DONE.
        // What we're really asserting: it didn't stay IN_FLIGHT.
        assertEquals(1, summary.done)
        assertEquals(
            PendingMutationStatus.Done.wireValue,
            dao.rows[id]!!.status,
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

    @Test
    fun sessionBoundaryMidBatchAbortsRemainingViaEpochGuard() = runTest {
        // [codex round-9 P1] The race we're closing: drain dequeues
        // + tryClaims row R under session A; a concurrent clearAll
        // (session boundary — bind clear / ledger switch) bumps the
        // epoch BEFORE row R's dispatch fires. Without the guard,
        // dispatcher would send R under session B's ApiService.
        //
        // We use [OutboxRepository.bumpSessionEpochForTesting] to
        // exercise EXACTLY this window: epoch advances mid-drain
        // WITHOUT also wiping the DAO (which clearAll() does
        // atomically in production; here we drive the partial
        // state the guard exists to defend against).
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        var dispatchCalls = 0
        val dispatcher = object : OutboxMutationDispatcher {
            override val type = PendingMutationType.PatchExpense
            override suspend fun dispatch(row: OutboxRow): DispatchResult {
                dispatchCalls++
                if (dispatchCalls == 1) {
                    // After the FIRST row's dispatch lands, simulate
                    // a session boundary by bumping the epoch. The
                    // SECOND row's post-claim check inside
                    // drainOnce sees the mismatch and aborts.
                    outbox.bumpSessionEpochForTesting()
                }
                return DispatchResult.Success()
            }
        }
        val engine = OutboxDrainEngine(outbox, listOf(dispatcher))
        // Two rows, different targets so dedup doesn't intervene.
        outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", "tok-1")
        outbox.enqueue(PendingMutationType.PatchExpense, "expense:2", "{}", "tok-2")

        val summary = engine.drainOnce()

        assertEquals(1, dispatchCalls, "second row must NOT be dispatched after the boundary")
        assertEquals(1, summary.done, "first row completed before the boundary")
        assertEquals(1, summary.aborted, "second row aborted by epoch check")
        assertEquals(2, summary.attempted)
    }

    @Test
    fun clearAllBeforeDrainProducesIdle() = runTest {
        // Complement to the mid-batch test: when clearAll fires
        // BEFORE drainOnce, the dequeue returns empty (DAO is
        // wiped) and the drain is IDLE. The epoch is bumped but
        // nobody's holding a pre-capture snapshot to compare
        // against. Verifies the trivial path.
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        var dispatchCalls = 0
        val dispatcher = object : OutboxMutationDispatcher {
            override val type = PendingMutationType.PatchExpense
            override suspend fun dispatch(row: OutboxRow): DispatchResult {
                dispatchCalls++
                return DispatchResult.Success()
            }
        }
        val engine = OutboxDrainEngine(outbox, listOf(dispatcher))
        outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", "tok-1")

        // Session boundary fires before the drain even starts.
        outbox.clearAll()
        val summary = engine.drainOnce()

        assertEquals(0, dispatchCalls)
        assertEquals(0, summary.attempted)
    }

    @Test
    fun clearAllBlocksUntilInFlightDispatchCompletes() = runTest {
        // Round-10 dispatch lease contract: once drain has passed the
        // post-claim epoch check and entered dispatcher.dispatch(row),
        // clearAll must wait. Otherwise the session coordinator can
        // rotate credentials while dispatch lazily reads the token.
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val dispatchEntered = CompletableDeferred<Unit>()
        val releaseDispatch = CompletableDeferred<Unit>()
        val dispatcher = object : OutboxMutationDispatcher {
            override val type = PendingMutationType.PatchExpense

            override suspend fun dispatch(row: OutboxRow): DispatchResult {
                dispatchEntered.complete(Unit)
                releaseDispatch.await()
                return DispatchResult.Success()
            }
        }
        val engine = OutboxDrainEngine(outbox, listOf(dispatcher))
        outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", "tok-1")

        val drain = async { engine.drainOnce() }
        dispatchEntered.await()
        var clearAllReturned = false
        val clearAll = launch {
            outbox.clearAll()
            clearAllReturned = true
        }
        yield()

        assertEquals(false, clearAllReturned, "clearAll must wait for in-flight dispatch")

        releaseDispatch.complete(Unit)
        val summary = drain.await()
        clearAll.join()

        assertEquals(true, clearAllReturned)
        assertEquals(1, summary.done)
        assertEquals(0, dao.rows.size, "clearAll wipes the row only after dispatch finishes")
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

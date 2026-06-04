package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.yield
import java.util.concurrent.atomic.AtomicInteger
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
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
            expectedRowVersion = 1L,
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
            expectedRowVersion = 1L,
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
            expectedRowVersion = 1L,
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
            expectedRowVersion = 1L,
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
            expectedRowVersion = 0L,
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
            expectedRowVersion = 0L,
        )
        outbox.enqueue(
            type = PendingMutationType.ConfirmExpense,
            targetId = "expense:99",
            payloadJson = "{}",
            expectedRowVersion = 0L,
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
            expectedRowVersion = 0L,
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
            StubDispatcher(result = DispatchResult.Success(newRowVersion = 2L)),
        )
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedRowVersion = 1L,
        )
        val secondId = outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedRowVersion = 1L,
        )

        val summary = engine.drainOnce()

        // Same-target dedup means only first runs this pass.
        assertEquals(1, summary.attempted)
        assertEquals(1, summary.done)

        val second = outbox.activeForTarget("expense:1").single { it.id == secondId }
        assertEquals(PendingMutationStatus.Pending, second.status)
        assertEquals(2L, second.expectedRowVersion)
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
            expectedRowVersion = 1L,
        )
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedRowVersion = 1L,
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
            expectedRowVersion = 0L,
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
                expectedRowVersion = 0L,
            )
        }
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:2",
            payloadJson = "{}",
            expectedRowVersion = 0L,
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
            expectedRowVersion = 0L,
        )
        outbox.markConflict(firstId, "stale")
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedRowVersion = 0L,
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
            expectedRowVersion = 0L,
        )
        outbox.markFailed(firstId, "bad payload")
        outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:1",
            payloadJson = "{}",
            expectedRowVersion = 0L,
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
        //
        // PR review #3: 改用 revertClaimWithoutAttempt, retryCount 不再因为 cancel 累加,
        // attemptedAt 抵消回 null。lastError 不写——保留先前任何诊断(本例 row 是新加的,
        // lastError 一直是 null)。
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val dispatcher = object : OutboxMutationDispatcher {
            override val type = PendingMutationType.PatchExpense
            override suspend fun dispatch(row: OutboxRow): DispatchResult {
                throw kotlinx.coroutines.CancellationException("worker cancelled")
            }
        }
        val engine = OutboxDrainEngine(outbox, listOf(dispatcher))
        outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 0L)

        val thrown = runCatching { engine.drainOnce() }.exceptionOrNull()
        assertTrue(
            thrown is kotlinx.coroutines.CancellationException,
            "CancellationException must propagate, got $thrown",
        )

        val row = outbox.activeForTarget("expense:1").single()
        assertEquals(PendingMutationStatus.Pending, row.status)
        assertEquals(null, row.lastError, "PR review #3: revertClaim 不写 lastError, 先前诊断保留")
        assertEquals(0, row.retryCount, "PR review #3: cancellation 不算尝试, retryCount 抵消回 0")
        assertEquals(null, row.attemptedAt, "PR review #3: attemptedAt 也抵消")
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
        val id = outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 0L)
        dao.rows[id] = dao.rows[id]!!.copy(
            status = PendingMutationStatus.InFlight.wireValue,
            attemptedAt = "2026-05-04T11:50:00Z",
        )

        val engine = OutboxDrainEngine(
            outbox,
            listOf(StubDispatcher(result = DispatchResult.Success())),
            // ADR-0042 §4.10: pin the engine clock to the same instant as the repo
            // clock so the new PENDING age-cap reaper sees this row's createdAt
            // (= now) as well inside the cap and leaves it for the IN_FLIGHT
            // recovery path. (In production both clocks are the real wall-clock;
            // the test must keep them consistent now that drainOnce reads a clock.)
            now = { now.toEpochMilli() },
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
            0L,
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
    fun concurrentDrainClaimRaceDispatchesRowOnce() = runTest {
        // Two drain workers can read the same PENDING batch before
        // either claims. The DAO-level status predicate must allow
        // exactly one claim, so only one dispatcher call may happen.
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val batchArrivals = AtomicInteger(0)
        val bothWorkersReadBatch = CompletableDeferred<Unit>()
        dao.beforeNextRunnableBatchReturn = {
            if (batchArrivals.incrementAndGet() == 2) {
                bothWorkersReadBatch.complete(Unit)
            }
            bothWorkersReadBatch.await()
        }
        val dispatchCalls = AtomicInteger(0)
        val dispatcher = object : OutboxMutationDispatcher {
            override val type = PendingMutationType.PatchExpense

            override suspend fun dispatch(row: OutboxRow): DispatchResult {
                dispatchCalls.incrementAndGet()
                return DispatchResult.Success()
            }
        }
        val firstEngine = OutboxDrainEngine(outbox, listOf(dispatcher))
        val secondEngine = OutboxDrainEngine(outbox, listOf(dispatcher))
        outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)

        val first = async { firstEngine.drainOnce() }
        val second = async { secondEngine.drainOnce() }
        val summaries = listOf(first.await(), second.await())

        assertEquals(1, dispatchCalls.get(), "row must be dispatched by only one worker")
        assertEquals(2, summaries.sumOf { it.attempted }, "both workers read the runnable row")
        assertEquals(1, summaries.sumOf { it.done })
        assertEquals(1, summaries.sumOf { it.raced })
        assertTrue(outbox.activeForTarget("expense:1").isEmpty())
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
        outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)
        outbox.enqueue(PendingMutationType.PatchExpense, "expense:2", "{}", 2L)

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
        outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)

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
        outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)

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

    @Test
    fun retryableFailureBeyondMaxAttemptsMarksRowFailed() = runTest {
        // codex P1 #7: 持续 RetryableFailure 不能无限重试。row.retryCount + 1 >= maxAttempts
        // 时转 FAILED, lastError 带 attempt 计数 + 原 server message, 用户在
        // SyncStatusScreen 看到 + 手动 retry(retryCount 由 DAO 在 resolveFailed.Retry
        // 时重置为 0)/丢弃。
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val engine = OutboxDrainEngine(
            outbox,
            listOf(StubDispatcher(result = DispatchResult.RetryableFailure("server 503"))),
            maxAttempts = 3,
        )
        outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)

        // Pass 1: retryCount 0 → 1, attempts=1 < 3, 仍 PENDING
        val first = engine.drainOnce()
        assertEquals(1, first.retryable)
        assertEquals(1, outbox.activeForTarget("expense:1").single().retryCount)
        assertEquals(PendingMutationStatus.Pending, outbox.activeForTarget("expense:1").single().status)

        // Pass 2: retryCount 1 → 2, attempts=2 < 3, 仍 PENDING
        engine.drainOnce()
        assertEquals(2, outbox.activeForTarget("expense:1").single().retryCount)
        assertEquals(PendingMutationStatus.Pending, outbox.activeForTarget("expense:1").single().status)

        // Pass 3: retryCount 2 → 3, attempts=3 >= 3 → markFailed
        val third = engine.drainOnce()
        assertEquals(1, third.failures, "exceeding maxAttempts must markFailed, not markRetryable")
        val row = outbox.activeForTarget("expense:1").single()
        assertEquals(PendingMutationStatus.Failed, row.status)
        assertTrue(
            row.lastError?.startsWith("max_attempts_exceeded(3/3):") == true,
            "lastError must encode attempts count + original message; got: ${row.lastError}",
        )

        // Pass 4: row 已 FAILED, dequeueNextRunnable 跳过, drain IDLE
        val fourth = engine.drainOnce()
        assertEquals(0, fourth.attempted)
    }

    @Test
    fun epochAbortMarksRowPendingNotInFlight() = runTest {
        // codex P2 #10 + PR review #9: epoch 失败时, tryClaim 已把 row 推到 IN_FLIGHT +
        // retryCount++ + attemptedAt=now, revertClaimWithoutAttempt 必须把这三件事都抵消:
        // 回 PENDING、retryCount-- (因为没真的 dispatch)、attemptedAt=null。lastError 不写
        // (保留先前 markRetryable 留下的诊断, abort 是窗口期事件不该淹没根因)。
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        var dispatchCalls = 0
        val dispatcher = object : OutboxMutationDispatcher {
            override val type = PendingMutationType.PatchExpense
            override suspend fun dispatch(row: OutboxRow): DispatchResult {
                dispatchCalls++
                if (dispatchCalls == 1) {
                    // 第 1 个 row 派发后 bump epoch, 让第 2 个在 post-claim 检查时 abort。
                    outbox.bumpSessionEpochForTesting()
                }
                return DispatchResult.Success()
            }
        }
        val engine = OutboxDrainEngine(outbox, listOf(dispatcher))
        outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)
        val secondId = outbox.enqueue(PendingMutationType.PatchExpense, "expense:2", "{}", 2L)
        // 预设第 2 个 row 已经有一次 markRetryable 留下的诊断, 验证 revertClaim 不会
        // 把它淹没。
        dao.rows[secondId] = dao.rows[secondId]!!.copy(lastError = "server 503")

        val summary = engine.drainOnce()
        assertEquals(1, summary.done, "first row landed before the boundary")
        assertEquals(1, summary.aborted, "second row aborted by epoch check")
        assertEquals(1, dispatchCalls, "aborted row must NOT be dispatched")

        val abortedRow = outbox.activeForTarget("expense:2").single()
        assertEquals(secondId, abortedRow.id)
        assertEquals(PendingMutationStatus.Pending, abortedRow.status)
        assertEquals(0, abortedRow.retryCount, "未真 dispatch 的 epoch-abort 必须抵消 tryClaim 的 retryCount++")
        assertEquals(null, abortedRow.attemptedAt, "PR review #9: attemptedAt 也应该被抵消, 否则 session flap 会让它无意义地推进")
        assertEquals("server 503", abortedRow.lastError, "PR review #9: revertClaim 不写 lastError, 先前 markRetryable 留下的根因诊断必须保留")
    }

    @Test
    fun cancellationMidDispatchRevertsClaimWithoutInflatingRetryCount() = runTest {
        // PR review #3: WorkManager OS-kill / process death 反复 cancel 一个 row 不能让
        // retryCount 静默累积到 max_attempts。CancellationException 路径用 revertClaim
        // (跟 epoch-abort 对称), 跨 N 次 cancel 后 retryCount 仍是 0。
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val dispatcher = object : OutboxMutationDispatcher {
            override val type = PendingMutationType.PatchExpense
            override suspend fun dispatch(row: OutboxRow): DispatchResult {
                throw CancellationException("WorkManager OS-kill")
            }
        }
        val engine = OutboxDrainEngine(outbox, listOf(dispatcher))
        outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)

        // 模拟连续 3 次 WorkManager cancel — 每次 drainOnce 都会跑到 dispatch 抛
        // CancellationException, 引擎应该 revertClaim 然后 rethrow。
        repeat(3) {
            assertFailsWith<CancellationException> {
                engine.drainOnce()
            }
        }

        // 3 次 cancel 后, retryCount 仍是 0(每次 revertClaim 抵消了 tryClaim 的 +1),
        // status 是 PENDING(下一次 drain 还能 claim)。max_attempts 没被消耗。
        val row = outbox.activeForTarget("expense:1").single()
        assertEquals(PendingMutationStatus.Pending, row.status)
        assertEquals(0, row.retryCount, "cancellation 不该算一次尝试, 否则 N 次 WorkManager kill 后 max_attempts 假性触发")
        assertEquals(null, row.attemptedAt)
    }

    @Test
    fun userRetryAfterMaxAttemptsResetsRetryCountAndReopensBudget() = runTest {
        // codex P1 #7 follow-up: max_attempts 触发后用户在 SyncStatusScreen 点 Retry,
        // 必须真的拿到完整重试预算 — retryCount 重置 0, 不然下次 drain 立刻又超
        // max_attempts → 永困 FAILED。本测试覆盖 PR description 承诺但之前没断言的核心
        // 行为(原 PR review P2 gap)。
        val dao = FakePendingMutationDao()
        val outbox = OutboxRepository(dao = dao)
        val engine = OutboxDrainEngine(
            outbox,
            listOf(StubDispatcher(result = DispatchResult.RetryableFailure("server 503"))),
            maxAttempts = 2,
        )
        val rowId = outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)

        // Pass 1+2: retryCount 0→1→2, attempts=2 >= 2 → FAILED
        engine.drainOnce()
        engine.drainOnce()
        val failed = outbox.activeForTarget("expense:1").single()
        assertEquals(PendingMutationStatus.Failed, failed.status)
        assertEquals(2, failed.retryCount)

        // 用户 Retry: row 回 PENDING + retryCount 重置 0 + lastError 记 manual_retry
        val resolved = outbox.resolveFailed(rowId, FailedResolution.Retry())
        assertEquals(true, resolved)
        val reset = outbox.activeForTarget("expense:1").single()
        assertEquals(PendingMutationStatus.Pending, reset.status)
        assertEquals(0, reset.retryCount, "用户 Retry 必须重置预算, 否则下次 drain 又被拦")
        assertEquals("manual_retry", reset.lastError)

        // Pass 3: 新预算, retryCount 0→1, attempts=1 < 2, 仍可继续重试
        val third = engine.drainOnce()
        assertEquals(1, third.retryable, "重置后的 row 必须重新进入重试循环, 不能再被 max_attempts 拦")
        assertEquals(1, outbox.activeForTarget("expense:1").single().retryCount)
    }

    @Test
    fun drainReapsOverAgePendingRowAndNeverDispatchesItWhileFreshRowRuns() = runTest {
        // ADR-0042 §4.10: at drain start the engine reaps PENDING rows older than
        // OUTBOX_PENDING_AGE_CAP_MILLIS (7d) to FAILED — never dispatching them,
        // because their idempotency key may have been purged server-side and a
        // replay would double-apply. A fresh PENDING row dispatches as usual.
        val dao = FakePendingMutationDao()
        val now = java.time.Instant.parse("2026-05-04T12:00:00Z")
        val outbox = OutboxRepository(
            dao = dao,
            clock = java.time.Clock.fixed(now, java.time.ZoneOffset.UTC),
        )
        val dispatchedTargets = mutableListOf<String>()
        val dispatcher = object : OutboxMutationDispatcher {
            override val type = PendingMutationType.PatchExpense
            override suspend fun dispatch(row: OutboxRow): DispatchResult {
                dispatchedTargets += row.targetId
                return DispatchResult.Success()
            }
        }
        // Engine clock fixed at the same instant as the repo clock so the cap math
        // (createdAt < now - 7d) is deterministic.
        val engine = OutboxDrainEngine(
            outbox,
            listOf(dispatcher),
            now = { now.toEpochMilli() },
        )
        // Stale row: enqueued, then back-dated a month (far past the 7-day cap).
        val staleId = outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)
        dao.rows[staleId] = dao.rows[staleId]!!.copy(createdAt = "2026-04-01T00:00:00.000Z")
        // Fresh row, different target — createdAt = now, inside the cap.
        outbox.enqueue(PendingMutationType.PatchExpense, "expense:2", "{}", 2L)

        val summary = engine.drainOnce()

        // Stale row reaped (FAILED, never dispatched); fresh row dispatched + DONE.
        assertEquals(1, summary.reaped, "the over-age PENDING row must be reaped")
        assertEquals(1, summary.attempted, "only the fresh row enters the batch")
        assertEquals(1, summary.done)
        assertTrue(summary.anythingChanged)
        assertEquals(
            listOf("expense:2"),
            dispatchedTargets,
            "the reaped row must NEVER be dispatched; only the fresh target runs",
        )
        val reapedRow = outbox.activeForTarget("expense:1").single()
        assertEquals(PendingMutationStatus.Failed, reapedRow.status)
        assertEquals("outbox_row_expired", reapedRow.lastError)
    }

    @Test
    fun drainWithOnlyAnOverAgeRowReapsItAndReportsChangedWithEmptyBatch() = runTest {
        // Reap-only pass: the single PENDING row is over-age, so after the reaper
        // flips it to FAILED the runnable batch is empty. drainOnce must still
        // report reaped > 0 + anythingChanged (it mutated the DB) rather than the
        // shared IDLE summary, so the scheduler/UI refreshes the FAILED banner.
        val dao = FakePendingMutationDao()
        val now = java.time.Instant.parse("2026-05-04T12:00:00Z")
        val outbox = OutboxRepository(
            dao = dao,
            clock = java.time.Clock.fixed(now, java.time.ZoneOffset.UTC),
        )
        var dispatchCalls = 0
        val dispatcher = object : OutboxMutationDispatcher {
            override val type = PendingMutationType.PatchExpense
            override suspend fun dispatch(row: OutboxRow): DispatchResult {
                dispatchCalls++
                return DispatchResult.Success()
            }
        }
        val engine = OutboxDrainEngine(outbox, listOf(dispatcher), now = { now.toEpochMilli() })
        val staleId = outbox.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)
        dao.rows[staleId] = dao.rows[staleId]!!.copy(createdAt = "2026-04-01T00:00:00.000Z")

        val summary = engine.drainOnce()

        assertEquals(0, dispatchCalls, "the reaped row must not be dispatched")
        assertEquals(0, summary.attempted, "no runnable work after the reap")
        assertEquals(1, summary.reaped)
        assertTrue(summary.anythingChanged, "a reap-only pass still changed the DB")
        assertEquals(PendingMutationStatus.Failed, outbox.activeForTarget("expense:1").single().status)
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

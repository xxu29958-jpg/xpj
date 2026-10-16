package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.CoroutineStart
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.onEach
import kotlinx.coroutines.flow.take
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.yield
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
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
 * Request parameters and recovery decisions stay here; generated DAO query
 * predicates belong to the instrumented Room tests
 * (``:app:connectedGrayDebugAndroidTest``), which run on the
 * path-filtered emulator lane (android-connected-test.yml).
 */
class OutboxRepositoryTest {

    @Test
    fun enqueuePersistsOriginalCommandsAndRequestsTheCurrentBoundBatch() = runTest {
        val dao = FakePendingMutationDao()
        val repo = testOutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))

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

        dao.runnableBatches += listOf(first, second)
        val runnable = repo.dequeueNextRunnable(limit = 10)
        assertEquals(listOf(first, second), runnable.map { it.id })
        assertEquals(PendingMutationStatus.Pending.wireValue, dao.rows.values.first().status)
    }

    @Test
    fun markDoneSetsCompletedAt() = runTest {
        val dao = FakePendingMutationDao()
        val repo = testOutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
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
        val repo = testOutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 0L)

        repo.markConflict(id, "账单已在其它端被修改，请刷新后重试。")

        val row = dao.rows[id]!!
        assertEquals(PendingMutationStatus.Conflict.wireValue, row.status)
        assertEquals("账单已在其它端被修改，请刷新后重试。", row.lastError)
    }

    @Test
    fun resolveConflictKeepMineRefreshesTokenAndReturnsToPending() = runTest {
        val dao = FakePendingMutationDao()
        val repo = testOutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
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
        val repo = testOutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
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
        val repo = testOutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
        val id = repo.enqueue(PendingMutationType.ConfirmExpense, "expense:1", "{}", 1L)
        repo.markConflict(id, "stale")

        repo.resolveConflict(id, ConflictResolution.KeepMine(freshToken = 2L))

        assertNull(dao.rows[id]!!.idempotencyKey, "keyless row must stay keyless after KeepMine")
    }

    @Test
    fun resolveFailedRetryExpiresOverAgeRowInsteadOfRequeuing() = runTest {
        // ADR-0042 §4.10: the reaper skips non-PENDING rows, so an old FAILED row
        // (max_attempts_exceeded) never carries outbox_row_expired. Retrying it would
        // flip it to PENDING with its original createdAt → the next drain instantly
        // re-reaps it (dead action + double-apply risk). resolveFailed must expire it.
        val dao = FakePendingMutationDao()
        val now = "2026-05-04T12:00:00Z"
        var scheduled = 0
        val repo = testOutboxRepository(dao = dao, clock = fixedClock(now), onEnqueued = { scheduled++ })

        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)
        repo.markFailed(id, "max_attempts_exceeded(10/10): server 503")
        dao.rows[id] = dao.rows[id]!!.copy(createdAt = "2026-04-01T00:00:00.000Z")

        dao.expiredBoundIds += id
        val changed = repo.resolveFailed(id, FailedResolution.Retry())

        assertEquals(BoundExpiryCall(id, testOutboxBinding().ownerStorageKey, "owner", "failed",
            "2026-04-27T12:00:00.000Z"), dao.boundExpiryCall)
        assertTrue(changed, "resolving an over-age FAILED row changes it (to expired)")
        val row = dao.rows[id]!!
        assertEquals(PendingMutationStatus.Failed.wireValue, row.status, "stays terminal, not re-queued")
        assertEquals("outbox_row_expired", row.lastError)
        assertEquals(1, scheduled, "Expiring the original must not schedule a replay")
    }

    @Test
    fun resolveConflictKeepMineExpiresOverAgeRowInsteadOfRequeuing() = runTest {
        // Same age guard on the keep-mine path — a rotated key can't undo a
        // committed-but-unseen original whose server key the retention purged.
        val dao = FakePendingMutationDao()
        val now = "2026-05-04T12:00:00Z"
        var scheduled = 0
        val repo = testOutboxRepository(dao = dao, clock = fixedClock(now), onEnqueued = { scheduled++ })

        val id = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 1L)
        repo.markConflict(id, "stale token")
        dao.rows[id] = dao.rows[id]!!.copy(createdAt = "2026-04-01T00:00:00.000Z")

        dao.expiredBoundIds += id
        val changed = repo.resolveConflict(id, ConflictResolution.KeepMine(freshToken = 9L))

        assertEquals(BoundExpiryCall(id, testOutboxBinding().ownerStorageKey, "owner", "conflict",
            "2026-04-27T12:00:00.000Z"), dao.boundExpiryCall)
        assertTrue(changed)
        val row = dao.rows[id]!!
        assertEquals(PendingMutationStatus.Failed.wireValue, row.status, "expired, not re-queued to PENDING")
        assertEquals("outbox_row_expired", row.lastError)
        assertEquals(1, scheduled, "Expiring the original must not schedule a replay")
    }

    @Test
    fun failedRowsKeepTheirUnresolvedState() = runTest {
        val dao = FakePendingMutationDao()
        val repo = testOutboxRepository(
            dao = dao,
            clock = fixedClock("2026-05-04T12:00:00Z"),
        )
        val failedId = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 0L)

        repo.markFailed(failedId, "user must decide")

        val row = dao.rows[failedId]
        assertNotNull(row)
        assertEquals(PendingMutationStatus.Failed.wireValue, row.status)
        assertNull(row.completedAt)
    }

    @Test
    fun resolveFailedRetryWithFreshTokenAlsoRefreshesIt() = runTest {
        val dao = FakePendingMutationDao()
        val repo = testOutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"))
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
    fun dequeuePassesTheCurrentBindingWithoutRewritingAnEarlierLedgerOriginal() = runTest {
        val dao = FakePendingMutationDao()
        var binding = testOutboxBinding().copy(serverUrl = "https://old.example.com", ledgerId = "ledger-a")
        val repo = testOutboxRepository(
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
        binding = testOutboxBinding().copy(serverUrl = "https://new.example.com", ledgerId = "ledger-b")
        val newRow = repo.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = "expense:2",
            payloadJson = "{}",
            expectedRowVersion = 2L,
        )

        dao.runnableBatches += listOf(newRow)
        val runnable = repo.dequeueNextRunnable(limit = 10, excludedIds = listOf(oldRow)).map { it.id }
        assertEquals(RunnableBatchCall(binding.ownerStorageKey, "ledger-b", listOf("in_flight", "conflict", "failed"),
            10, listOf(oldRow)), dao.batchCalls.single())

        assertEquals(listOf(newRow), runnable)
        assertEquals("https://old.example.com", dao.rows[oldRow]?.serverUrl)
        assertEquals("ledger-a", dao.rows[oldRow]?.ledgerId)
    }

    @Test
    fun observeStatusAggregatesCurrentBindingOnly() = runTest {
        val dao = FakePendingMutationDao()
        var binding = testOutboxBinding().copy(serverUrl = "https://api.example.com", ledgerId = "active")
        val repo = testOutboxRepository(
            dao = dao,
            clock = fixedClock("2026-05-04T00:00:00Z"),
            bindingProvider = { binding },
        )
        val activePending = repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 0L)
        val activeConflict = repo.enqueue(PendingMutationType.PatchExpense, "expense:2", "{}", 0L)
        repo.markConflict(activeConflict, "stale")

        binding = testOutboxBinding().copy(serverUrl = "https://api.example.com", ledgerId = "other")
        repo.enqueue(PendingMutationType.PatchExpense, "expense:3", "{}", 0L)
        binding = testOutboxBinding().copy(serverUrl = "https://api.example.com", ledgerId = "active")

        val status = repo.observeStatus().first()

        assertEquals(1, status.queueDepth)
        assertEquals(listOf(activeConflict), status.conflicts.map { it.id })
        assertTrue(status.needsUserAction)
        assertEquals("active", dao.rows[activePending]?.ledgerId)
    }

    @Test
    fun routeChangeKeepsRowsVisibleForTheSameServerIdentity() = runTest {
        val dao = FakePendingMutationDao()
        var binding = testOutboxBinding().copy(serverUrl = "https://old.example.com", ledgerId = "active")
        val unchangedLedgerSignal = MutableStateFlow(binding)
        val repo = testOutboxRepository(
            dao = dao,
            bindingProvider = { binding },
            bindingChanges = unchangedLedgerSignal,
        )
        repo.enqueue(PendingMutationType.PatchExpense, "expense:1", "{}", 0L)
        val initialObserved = CompletableDeferred<Unit>()
        val observed = async(start = CoroutineStart.UNDISPATCHED) {
            repo.observeStatus().map { it.queueDepth }
                .onEach { initialObserved.complete(Unit) }
                .take(2)
                .toList()
        }
        initialObserved.await()

        repo.withBindingTransition {
            binding = testOutboxBinding().copy(serverUrl = "https://new.example.com", ledgerId = "active")
        }

        assertEquals(listOf(1, 1), observed.await())
    }

    @Test
    fun concurrentBindingInvalidationsRetargetToFinalServer() = runTest {
        val dao = FakePendingMutationDao()
        var binding = testOutboxBinding().copy(serverUrl = "https://old.example.com", ledgerId = "active")
        val unchangedLedgerSignal = MutableStateFlow(binding)
        val repo = testOutboxRepository(
            dao = dao,
            bindingProvider = { binding },
            bindingChanges = unchangedLedgerSignal,
        )
        repo.enqueue(PendingMutationType.PatchExpense, "old", "{}", 0L)
        binding = testOutboxBinding().copy(
            serverUrl = "https://middle.example.com",
            ledgerId = "active",
            owner = testOwner("20000000"),
        )
        repo.enqueue(PendingMutationType.PatchExpense, "middle", "{}", 0L)
        binding = testOutboxBinding().copy(
            serverUrl = "https://final.example.com",
            ledgerId = "active",
            owner = testOwner("30000000"),
        )
        repo.enqueue(PendingMutationType.PatchExpense, "final-1", "{}", 0L)
        repo.enqueue(PendingMutationType.PatchExpense, "final-2", "{}", 0L)
        binding = testOutboxBinding().copy(serverUrl = "https://old.example.com", ledgerId = "active")

        val initialObserved = CompletableDeferred<Unit>()
        val finalDepth = async(start = CoroutineStart.UNDISPATCHED) {
            repo.observeStatus().map { it.queueDepth }
                .onEach { depth -> if (depth == 1) initialObserved.complete(Unit) }
                .first { depth -> depth == 2 }
        }
        initialObserved.await()
        val firstTransitionEntered = CompletableDeferred<Unit>()
        val releaseFirstTransition = CompletableDeferred<Unit>()
        val firstTransition = launch {
            repo.withBindingTransition {
                binding = testOutboxBinding().copy(
                    serverUrl = "https://middle.example.com",
                    ledgerId = "active",
                    owner = testOwner("20000000"),
                )
                firstTransitionEntered.complete(Unit)
                releaseFirstTransition.await()
            }
        }
        firstTransitionEntered.await()
        val finalTransition = launch {
            repo.withBindingTransition {
                binding = testOutboxBinding().copy(
                    serverUrl = "https://final.example.com",
                    ledgerId = "active",
                    owner = testOwner("30000000"),
                )
            }
        }

        releaseFirstTransition.complete(Unit)
        firstTransition.join()
        finalTransition.join()

        assertEquals(2, finalDepth.await())
    }

    @Test
    fun aliasMigrationRejectsDifferentCanonicalOrigins() {
        assertFailsWith<IllegalArgumentException> {
            OutboxServerAliasMigration(
                oldServerUrl = "https://old.example.com",
                newServerUrl = "https://new.example.com",
                ledgerId = "active",
            )
        }
    }

    @Test
    fun recoverStaleInFlightPassesTheCurrentBindingAndFixedUtcCutoff() = runTest {
        val dao = FakePendingMutationDao()
        var binding = testOutboxBinding().copy(ledgerId = "previous")
        val repo = testOutboxRepository(dao = dao, clock = fixedClock("2026-05-04T00:00:00Z"),
            bindingProvider = { binding })
        binding = binding.copy(ledgerId = "active")
        assertEquals(0, repo.recoverStaleInFlight())
        assertEquals(Triple(binding.ownerStorageKey, "active", "2026-05-03T23:55:00.000Z"), dao.staleRecoveryCall)
    }

    @Test
    fun enqueueWaitsForBindingTransitionAndCannotPersistMixedBinding() = runTest {
        val dao = FakePendingMutationDao()
        var binding = testOutboxBinding().copy(serverUrl = "https://old.example.com", ledgerId = "ledger-a")
        val repo = testOutboxRepository(
            dao = dao,
            clock = fixedClock("2026-05-04T00:00:00Z"),
            bindingProvider = { binding },
        )
        val transitionStarted = CompletableDeferred<Unit>()
        val releaseTransition = CompletableDeferred<Unit>()

        val transition = async {
            repo.withBindingTransition {
                binding = testOutboxBinding().copy(serverUrl = "https://new.example.com", ledgerId = "ledger-a")
                transitionStarted.complete(Unit)
                releaseTransition.await()
                binding = testOutboxBinding().copy(serverUrl = "https://new.example.com", ledgerId = "ledger-b")
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

    private fun testOwner(prefix: String): OutboxOwnerIdentity = requireNotNull(
        OutboxOwnerIdentity.fromOrNull(
            serverId = "$prefix-0000-0000-0000-000000000001",
            dataGeneration = "$prefix-0000-0000-0000-000000000002",
            accountPublicId = "$prefix-0000-0000-0000-000000000003",
            devicePublicId = "$prefix-0000-0000-0000-000000000004",
        ),
    )
}

// FakePendingMutationDao moved to its own file so OutboxDrainEngineTest
// can reuse it without a file-private declaration.

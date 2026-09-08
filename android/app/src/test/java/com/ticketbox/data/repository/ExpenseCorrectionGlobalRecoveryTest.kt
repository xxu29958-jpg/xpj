package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.ExpenseEntity
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.viewmodel.OutboxRecoveryRepositories
import com.ticketbox.viewmodel.OutboxStatusViewModel
import com.ticketbox.viewmodel.outboxStatusViewModelFactory
import java.io.IOException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.job
import kotlinx.coroutines.joinAll
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.selects.select
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue
import androidx.lifecycle.viewModelScope

/** Real facade, recovery factory and one shared Outbox; only HTTP and storage adapters are fakes. */
@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseCorrectionGlobalRecoveryTest {
    private val dispatcher = StandardTestDispatcher()
    private val harness = CorrectionRecoveryHarness()

    @BeforeTest
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @AfterTest
    fun tearDown() = runTest(dispatcher) {
        try {
            harness.close()
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun conflictDropWaitsForTheCurrentFactAndCachesItBeforeRemovingTheIntent() = runTest(dispatcher) {
        val api = RecoveryApi(harness.confirmedDto())
        val fixture = harness.fixture(api)
        val row = harness.seedCorrection(fixture, PendingMutationStatus.Conflict)
        advanceUntilIdle()
        val original = fixture.queue.rows.getValue(row.id)
        val response = CompletableDeferred<ExpenseDto>()
        val readStarted = CompletableDeferred<Unit>()
        api.reads.clear()
        api.read = { readStarted.complete(Unit); response.await() }

        val operation = fixture.startRecovery { fixture.vm.dropMine(row) }
        awaitReadOrFinished(operation, readStarted)

        assertEquals(original, fixture.queue.rows[row.id], "A pending current-fact GET must retain the original intent")
        assertEquals(listOf(42L), api.reads)
        assertEquals(row.id, fixture.vm.uiState.value.busyRowId)
        val current = harness.confirmedDto().copy(merchant = "Server correction", rowVersion = 8L)
        response.complete(current)
        operation.join()
        advanceUntilIdle()

        val cached = fixture.repository.fetchExpenseFromLocalCache(42L).getOrThrow()
        assertEquals(current.merchant, cached.merchant)
        assertEquals(current.rowVersion, cached.rowVersion)
        assertEquals(current.amountCents, cached.amountCents)
        assertTrue(fixture.queue.rows.isEmpty())
        assertTrue(fixture.vm.uiState.value.correctionObservation.corrections.isEmpty())
        assertNull(fixture.vm.uiState.value.busyRowId)
        assertNull(fixture.vm.uiState.value.message)
    }

    @Test
    fun unknownResultDropCanRecoverAfterAReadFailureWithoutDemandingANewerVersion() = runTest(dispatcher) {
        val api = RecoveryApi(harness.confirmedDto())
        val fixture = harness.fixture(api)
        val row = harness.seedCorrection(fixture, PendingMutationStatus.Failed)
        advanceUntilIdle()
        val original = fixture.queue.rows.getValue(row.id)
        api.reads.clear()
        api.read = { throw IOException("current fact unavailable") }

        fixture.startRecovery { fixture.vm.dropFailed(row) }.join()
        advanceUntilIdle()

        assertEquals(original, fixture.queue.rows[row.id], "An unknown outcome is still recoverable after GET failure")
        assertEquals(listOf(42L), api.reads)
        assertNotNull(fixture.vm.uiState.value.message)
        assertEquals(MessageTone.Danger, fixture.vm.uiState.value.messageTone)
        assertNull(fixture.vm.uiState.value.busyRowId)
        api.read = { harness.confirmedDto() }
        fixture.startRecovery { fixture.vm.dropFailed(row) }.join()
        advanceUntilIdle()

        assertEquals(7L, fixture.repository.fetchExpenseFromLocalCache(42L).getOrThrow().rowVersion)
        assertEquals(listOf(42L, 42L), api.reads)
        assertTrue(fixture.queue.rows.isEmpty(), "An unchanged authoritative version is a valid recovery result")
        assertNull(fixture.vm.uiState.value.message)
    }

    @Test
    fun cacheFailureKeepsTheOriginalRowUntilTheSameDropCanComplete() = runTest(dispatcher) {
        val stored = FakeExpenseDao()
        var rejectCache = false
        val cache = object : ExpenseDao by stored {
            override suspend fun upsertByServerIdForLedger(ledgerId: String, expense: ExpenseEntity): Boolean {
                if (rejectCache) throw IOException("cache unavailable")
                return stored.upsertByServerIdForLedger(ledgerId, expense)
            }
        }
        val api = RecoveryApi(harness.confirmedDto())
        val fixture = harness.fixture(api, cache)
        val row = harness.seedCorrection(fixture, PendingMutationStatus.Conflict)
        advanceUntilIdle()
        val original = fixture.queue.rows.getValue(row.id)
        val current = harness.confirmedDto().copy(merchant = "Refreshed", rowVersion = 8L)
        api.read = { current }
        rejectCache = true
        fixture.startRecovery { fixture.vm.dropMine(row) }.join()
        advanceUntilIdle()

        assertEquals(original, fixture.queue.rows[row.id])
        assertEquals(7L, fixture.repository.fetchExpenseFromLocalCache(42L).getOrThrow().rowVersion)
        assertNotNull(fixture.vm.uiState.value.message)
        rejectCache = false
        fixture.startRecovery { fixture.vm.dropMine(row) }.join()
        advanceUntilIdle()

        assertTrue(fixture.queue.rows.isEmpty())
        val cached = fixture.repository.fetchExpenseFromLocalCache(42L).getOrThrow()
        assertEquals(current.merchant, cached.merchant)
        assertEquals(current.rowVersion, cached.rowVersion)
    }

    @Test
    fun aNowPendingRootRetiresOnlyItsConfirmedCacheAndOffsetsBeforeLocalDiscard() = runTest(dispatcher) {
        val api = RecoveryApi(harness.confirmedDto())
        val fixture = harness.fixture(api)
        val row = harness.seedCorrection(fixture, PendingMutationStatus.Conflict)
        val offset = expenseFactBundleDtoFixture().toCacheProjection("owner").activeOffsets.single()
            .copy(publicId = "target-offset", rootServerId = 42L)
        fixture.cache.insert(harness.confirmedDto().copy(id = 99L, publicId = "other-root").toEntity("owner"))
        fixture.cache.insert(harness.confirmedDto().toEntity("other-ledger"))
        fixture.cache.upsertConfirmedStreamOffsets(listOf(offset,
            offset.copy(publicId = "other-root-offset", rootServerId = 99L),
            offset.copy(ledgerId = "other-ledger")))
        advanceUntilIdle()
        api.read = { harness.confirmedDto().copy(status = "pending", rowVersion = 8L, confirmedAt = null) }

        fixture.startRecovery { fixture.vm.dropMine(row) }.join()
        advanceUntilIdle()

        assertEquals(listOf(99L), fixture.cache.getConfirmed("owner").map { it.serverId })
        assertEquals(listOf("other-root-offset"), fixture.cache.getConfirmedStreamOffsets("owner").map { it.publicId })
        assertEquals(listOf(42L), fixture.cache.getConfirmed("other-ledger").map { it.serverId })
        assertEquals(listOf("target-offset"), fixture.cache.getConfirmedStreamOffsets("other-ledger").map { it.publicId })
        assertTrue(fixture.queue.rows.isEmpty())
        assertNull(fixture.vm.uiState.value.message)
    }

    @Test
    fun bindingChangeDuringGlobalDropKeepsTheOriginalIntentAndCache() = runTest(dispatcher) {
        val api = RecoveryApi(harness.confirmedDto())
        val token = harness.token()
        val fixture = harness.fixture(api, token = token)
        val row = harness.seedCorrection(fixture, PendingMutationStatus.Conflict)
        advanceUntilIdle()
        val original = fixture.queue.rows.getValue(row.id)
        val response = CompletableDeferred<ExpenseDto>()
        val readStarted = CompletableDeferred<Unit>()
        api.read = { readStarted.complete(Unit); response.await() }
        val operation = fixture.startRecovery { fixture.vm.dropMine(row) }
        awaitReadOrFinished(operation, readStarted)
        assertEquals(original, fixture.queue.rows[row.id])
        token.switchLedgerForFixture("other-ledger", "Another family", role = "member")
        response.complete(harness.confirmedDto().copy(merchant = "Old binding reply", rowVersion = 8L))
        operation.join()
        advanceUntilIdle()

        assertEquals(original, fixture.queue.rows[row.id])
        assertEquals(7L, fixture.cache.getConfirmed("owner").single().rowVersion)
        assertTrue(fixture.cache.getConfirmed("other-ledger").isEmpty())
        assertEquals("other-ledger", fixture.vm.uiState.value.binding?.ledgerId)
        assertTrue(fixture.vm.uiState.value.correctionObservation.corrections.isEmpty())
        assertNull(fixture.vm.uiState.value.message, "A former binding cannot publish its recovery failure here")
        assertNull(fixture.vm.uiState.value.busyRowId)
    }

    @Test
    fun knownTargetRefusalAllowsExplicitLocalDiscardWithoutInventingNewServerFacts() = runTest(dispatcher) {
        val api = RecoveryApi(harness.confirmedDto())
        val fixture = harness.fixture(api)
        val row = harness.seedCorrection(fixture, PendingMutationStatus.Failed)
        fixture.outbox.markFailed(row.id, "correction_target_unavailable")
        advanceUntilIdle()
        val current = fixture.vm.uiState.first { state ->
            state.status.failed.any { it.id == row.id && it.lastError == "correction_target_unavailable" }
        }.status.failed.single()
        api.reads.clear()
        api.read = { throw IOException("not a fact refresh") }

        fixture.startRecovery { fixture.vm.dropFailed(current) }.join()
        advanceUntilIdle()

        assertTrue(fixture.queue.rows.isEmpty())
        assertTrue(api.reads.isEmpty())
        assertEquals(7L, fixture.repository.fetchExpenseFromLocalCache(42L).getOrThrow().rowVersion)
    }

    @Test
    fun aConcurrentRetryCannotBeDeletedByAnOlderDropRead() = runTest(dispatcher) {
        val api = RecoveryApi(harness.confirmedDto())
        val fixture = harness.fixture(api)
        val row = harness.seedCorrection(fixture, PendingMutationStatus.Failed)
        advanceUntilIdle()
        val response = CompletableDeferred<ExpenseDto>()
        val readStarted = CompletableDeferred<Unit>()
        api.reads.clear()
        api.read = { readStarted.complete(Unit); response.await() }
        val operation = fixture.startRecovery { fixture.vm.dropFailed(row) }
        awaitReadOrFinished(operation, readStarted)
        assertEquals(listOf(42L), api.reads)

        assertTrue(fixture.outbox.resolveFailed(row.id, FailedResolution.Retry()))
        val retried = fixture.queue.rows.getValue(row.id)
        assertEquals(PendingMutationStatus.Pending.wireValue, retried.status)
        response.complete(harness.confirmedDto())
        operation.join()
        advanceUntilIdle()

        assertEquals(retried, fixture.queue.rows[row.id])
        assertNotNull(fixture.vm.uiState.value.message)
        assertEquals(MessageTone.Danger, fixture.vm.uiState.value.messageTone)
        assertNull(fixture.vm.uiState.value.busyRowId)
    }

    @Test
    fun aDelayedPendingReadCannotEraseANewerConfirmedProjection() = runTest(dispatcher) {
        val api = RecoveryApi(harness.confirmedDto())
        val fixture = harness.fixture(api)
        val row = harness.seedCorrection(fixture, PendingMutationStatus.Conflict)
        advanceUntilIdle()
        val response = CompletableDeferred<ExpenseDto>()
        val readStarted = CompletableDeferred<Unit>()
        api.reads.clear()
        api.read = { readStarted.complete(Unit); response.await() }
        val operation = fixture.startRecovery { fixture.vm.dropMine(row) }
        awaitReadOrFinished(operation, readStarted)
        assertEquals(listOf(42L), api.reads)

        val newer = harness.confirmedDto().copy(merchant = "A newer confirmed fact", rowVersion = 9L)
        fixture.cache.upsertByServerIdForLedger("owner", newer.toEntity("owner"))
        val offset = expenseFactBundleDtoFixture().toCacheProjection("owner").activeOffsets.single()
            .copy(publicId = "newer-offset", rootServerId = 42L)
        fixture.cache.upsertConfirmedStreamOffsets(listOf(offset))
        response.complete(harness.confirmedDto().copy(status = "pending", rowVersion = 8L, confirmedAt = null))
        operation.join()
        advanceUntilIdle()

        assertEquals(newer.merchant, fixture.repository.fetchExpenseFromLocalCache(42L).getOrThrow().merchant)
        assertEquals(9L, fixture.cache.getConfirmed("owner").single().rowVersion)
        assertEquals(listOf(offset), fixture.cache.getConfirmedStreamOffsets("owner"))
        assertTrue(fixture.queue.rows.isEmpty())
        assertNull(fixture.vm.uiState.value.message)
    }

    @Test
    fun unsupportedOriginalInputStillHasAnExplicitLocalDiscardWithoutAGet() = runTest(dispatcher) {
        val api = RecoveryApi(harness.confirmedDto())
        val fixture = harness.fixture(api)
        val original = ExpenseCorrectionRequestDto(7L, "Old original reason", merchant = "Original input")
        val payload = OutboxAdapterGraph().legacyCorrectionAdapter.toJson(original)
        val id = fixture.outbox.enqueue(PendingMutationType.CorrectExpense, "expense:42", payload, 7L, "legacy-key")
        fixture.outbox.markFailed(id, "correction_requires_review")
        advanceUntilIdle()
        val pending = fixture.vm.uiState.value.correctionObservation.corrections.single()
        assertFalse(pending.hasSupportedIntent)
        assertEquals(original, pending.legacyRequest)

        fixture.startRecovery { fixture.vm.dropFailed(pending.row) }.join()
        advanceUntilIdle()

        assertTrue(fixture.queue.rows.isEmpty())
        assertTrue(api.reads.isEmpty())
    }

}

private class CorrectionRecoveryHarness : ExpensePendingRepositoryOutboxTestBase() {
    private val recoveryModels = mutableListOf<OutboxStatusViewModel>()

    suspend fun close() {
        val jobs = recoveryModels.map { it.viewModelScope.coroutineContext.job }
        jobs.forEach { it.cancel() }
        jobs.joinAll()
    }
    fun token(): TestSessionFixture = seededTokenStore()

    fun fixture(
        api: ApiService,
        cache: ExpenseDao = FakeExpenseDao(),
        token: TestSessionFixture = seededTokenStore(),
    ): RecoveryFixture {
        val queue = FakePendingMutationDao()
        val binding = testServerSessionBinding(TestApiServiceFactory(api), seededSettingsStore(), token)
        val outbox = OutboxRepository(queue, bindingProvider = { binding.sessionStore.currentSession().toOutboxBinding() },
            onRowsDeleted = {})
        val repository = ExpenseRepository(cache, binding, deviceNameProvider = { "Android Test" },
            offlineMutations = testExpenseOfflineMutationWiring(outbox))
        val adapters = OutboxAdapterGraph()
        val consumers = OutboxRecoveryRepositories(
            debtCreation = DebtCreationRepository(binding.apiProvider, outbox, adapters.debtCreateAdapter),
            recurringOccurrences = null,
            incomePlans = IncomePlanRepository(binding.apiProvider, outbox, adapters.incomePlanUpdateAdapter),
            debtAdjustments = DebtAdjustmentRepository(binding.apiProvider, outbox, adapters.debtAdjustmentAdapter),
            goalEdits = GoalEditRepository(binding.apiProvider, outbox, adapters.goalUpdateAdapter, adapters.goalReceiptAdapter),
        )
        val vm = outboxStatusViewModelFactory(outbox, repository, consumers).create(OutboxStatusViewModel::class.java)
        recoveryModels += vm
        return RecoveryFixture(repository, outbox, queue, cache, vm)
    }

    suspend fun seedCorrection(fixture: RecoveryFixture, status: PendingMutationStatus): OutboxRow {
        val expense = fixture.repository.fetchExpense(42L).getOrThrow()
        val access = assertNotNull(fixture.repository.observeCorrections().first().access)
        val id = fixture.repository.submitCorrection(access.binding, expense,
            ExpenseCorrectionDraft(reason = "Original correction", merchant = "My original merchant")).getOrThrow()
        if (status == PendingMutationStatus.Conflict) fixture.outbox.markConflict(id, "state_conflict")
        else fixture.outbox.markFailed(id, "correction_delivery_unknown")
        val pending = fixture.repository.observeCorrections().first().corrections.single()
        assertTrue(pending.hasSupportedIntent)
        assertEquals(status, pending.row.status)
        assertNotNull(pending.row.idempotencyKey)
        fixture.vm.uiState.first { state ->
            state.correctionObservation.corrections.any { it.row.id == id && it.row.status == status }
        }
        return pending.row
    }

    fun confirmedDto(): ExpenseDto = successExpenseDto().copy(
        status = "confirmed", merchant = "Original confirmed merchant", rowVersion = 7L,
        confirmedAt = "2026-05-20T12:00:05.000Z",
    )

}

private data class RecoveryFixture(
    val repository: ExpenseRepository,
    val outbox: OutboxRepository,
    val queue: FakePendingMutationDao,
    val cache: ExpenseDao,
    val vm: OutboxStatusViewModel,
)

private fun RecoveryFixture.startRecovery(action: () -> Unit): Job {
    val scopeJob = vm.viewModelScope.coroutineContext.job
    val existing = scopeJob.children.toSet()
    action()
    return scopeJob.children.single { it !in existing }
}

private suspend fun awaitReadOrFinished(operation: Job, readStarted: CompletableDeferred<Unit>) {
    select<Unit> {
        readStarted.onAwait { }
        operation.onJoin { }
    }
}

private class RecoveryApi(initial: ExpenseDto) : ApiService by FakeApiService(mutableListOf(), 0) {
    val reads = mutableListOf<Long>()
    var read: suspend () -> ExpenseDto = { initial }

    override suspend fun expense(id: Long): ExpenseDto {
        reads += id
        return read()
    }
}

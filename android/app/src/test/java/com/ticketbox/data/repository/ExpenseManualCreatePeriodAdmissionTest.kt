package com.ticketbox.data.repository

import androidx.lifecycle.SavedStateHandle
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.ui.navigation.RecurringPaymentDraft
import com.ticketbox.ui.navigation.RecurringPaymentDraftStore
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.yield
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
import kotlin.test.assertTrue

internal class ExpenseManualCreatePeriodAdmissionTest : ExpensePendingRepositoryOutboxTestBase() {
    private val activeLedger = "family"

    private class OfflineApi : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
        override suspend fun createManualExpense(request: ExpenseManualCreateRequestDto): ExpenseDto {
            throw IOException("airplane mode")
        }
    }

    private fun outbox(dao: FakePendingMutationDao) = testOutboxRepository(
        dao = dao,
        bindingProvider = { testOutboxBinding(ledgerId = activeLedger) },
    )

    private fun createRepo(dao: FakeExpenseDao, outbox: OutboxRepository) = ExpenseRepository(
        expenseDao = dao,
        binding = testServerSessionBinding(
            apiClient = TestApiServiceFactory(OfflineApi()),
            settingsStore = seededSettingsStore(),
            tokenStore = ledgerSessionFixture(activeLedger, "家庭账本"),
        ),
        deviceNameProvider = { "Android Test" },
        offlineMutations = ExpenseOfflineMutationWiring(
            outbox = outbox,
            expenseStateTokenAdapter = com.ticketbox.OutboxAdapterGraph().expenseStateTokenAdapter,
            recognizeTextAdapter = com.ticketbox.OutboxAdapterGraph().recognizeTextAdapter,
            patchExpenseAdapter = moshi().adapter(com.ticketbox.data.remote.dto.ExpenseUpdateRequest::class.java),
            manualCreateAdapter = moshi().adapter(ExpenseManualCreateRequestDto::class.java),
            recurringPaymentCreateAdapter = com.ticketbox.OutboxAdapterGraph().recurringPaymentCreateAdapter,
            correctionAdapter = com.ticketbox.OutboxAdapterGraph().correctionAdapter,
            billSplitReceiptAdapter = com.ticketbox.OutboxAdapterGraph().billSplitReceiptAdapter,
            billSplitCreateAdapter = com.ticketbox.OutboxAdapterGraph().billSplitCreateAdapter,
            legacyCorrectionAdapter = com.ticketbox.OutboxAdapterGraph().legacyCorrectionAdapter,
        ),
    )

    @Test
    fun nullGenerationCreateIsBlockedWithoutEnqueue() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.write(keptDraft("current-b"))
        val blocked = repo.manualCreation.create(
            draft, binding, "current-b", RecurringPaymentOrigin("rec-1", "2026-08"),
        ).getOrThrow()
        assertEquals(
            ManualExpenseCreateAdmission.Blocked(RecurringPaymentAdmissionBlock.MissingGeneration),
            blocked,
        )
        assertEquals(0, pendingDao.rows.size)
        assertEquals("当前草稿", store.read("current-b")?.note)
    }

    @Test
    fun exactGenerationReusesTheOriginalClientRef() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.write(keptDraft("current-b"))
        val origin = RecurringPaymentOrigin("rec-1", "2026-08", 7)
        repo.manualCreation.create(draft, binding, "origin-a", origin).getOrThrow()
        val reused = repo.manualCreation.create(draft.copy(merchant = "改过的商户"), binding, "current-b", origin).getOrThrow()
        assertEquals("origin-a", (reused as ManualExpenseCreateAdmission.Accepted).clientRef)
        assertEquals(1, pendingDao.rows.size)
        assertEquals("expense:local:origin-a", pendingDao.rows.values.single().targetId)
        assertEquals("当前草稿", store.read("current-b")?.note)
    }

    @Test
    fun newerActiveOriginBlocksOlderGenerationCreate() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.write(keptDraft("current-b"))
        repo.manualCreation.create(draft, binding, "origin-a", RecurringPaymentOrigin("rec-1", "2026-08", 7)).getOrThrow()
        val blocked = repo.manualCreation.create(
            draft.copy(merchant = "改过的商户"),
            binding,
            "current-b",
            RecurringPaymentOrigin("rec-1", "2026-08", 5),
        ).getOrThrow()
        assertEquals(
            ManualExpenseCreateAdmission.Blocked(RecurringPaymentAdmissionBlock.DifferentGeneration),
            blocked,
        )
        assertEquals(1, pendingDao.rows.size)
        assertEquals("expense:local:origin-a", pendingDao.rows.values.single().targetId)
        assertEquals("当前草稿", store.read("current-b")?.note)
    }

    @Test
    fun duplicateActivePeriodOriginsFailClosed() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        repo.manualCreation.create(draft, binding, "origin-a", RecurringPaymentOrigin("rec-1", "2026-08", 5)).getOrThrow()
        val first = pendingDao.rows.values.single()
        val graph = com.ticketbox.OutboxAdapterGraph()
        pendingDao.insert(
            first.copy(
                id = 0L,
                targetId = "expense:local:origin-c",
                payload = encodeManualCreatePayload(
                    graph.manualCreateAdapter,
                    graph.recurringPaymentCreateAdapter,
                    draft.toManualCreateRequest(clientRef = "origin-c"),
                    RecurringPaymentOrigin("rec-1", "2026-08", 7),
                ),
            ),
        )
        assertTrue(
            repo.manualCreation.create(draft, binding, "current-b", RecurringPaymentOrigin("rec-1", "2026-08", 9)).isFailure,
        )
        assertEquals(
            RecurringPaymentOriginAdopt.Conflict,
            repo.manualCreation.adoptOrigin(binding, "legacy-ref", "rec-1", "2026-08", 9),
        )
        assertEquals(2, pendingDao.rows.size)
        assertTrue(pendingDao.rows.values.none { it.targetId == "expense:local:current-b" })
    }

    @Test
    fun aWinsAdmissionLockBlocksTheOlderGeneration() = runTest {
        val entered = CompletableDeferred<Unit>()
        val hold = CompletableDeferred<Unit>()
        val pendingDao = FakePendingMutationDao().apply {
            beforeInsert = {
                entered.complete(Unit)
                hold.await()
            }
        }
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.write(keptDraft("current-b"))
        val aJob = launch {
            repo.manualCreation.create(draft, binding, "origin-a", RecurringPaymentOrigin("rec-1", "2026-08", 7)).getOrThrow()
        }
        entered.await()
        var bAdmission: ManualExpenseCreateAdmission? = null
        val bJob = launch {
            bAdmission = repo.manualCreation.create(
                draft.copy(merchant = "改过的商户"),
                binding,
                "current-b",
                RecurringPaymentOrigin("rec-1", "2026-08", 5),
            ).getOrThrow()
        }
        yield()
        assertTrue(aJob.isActive)
        assertTrue(bJob.isActive)
        hold.complete(Unit)
        aJob.join()
        bJob.join()
        assertEquals(
            ManualExpenseCreateAdmission.Blocked(RecurringPaymentAdmissionBlock.DifferentGeneration),
            bAdmission,
        )
        assertEquals(1, pendingDao.rows.size)
        assertEquals("expense:local:origin-a", pendingDao.rows.values.single().targetId)
        assertEquals("当前草稿", store.read("current-b")?.note)
    }

    @Test
    fun bWinsAdmissionLockBlocksTheNewerGeneration() = runTest {
        val entered = CompletableDeferred<Unit>()
        val hold = CompletableDeferred<Unit>()
        val pendingDao = FakePendingMutationDao().apply {
            beforeInsert = {
                entered.complete(Unit)
                hold.await()
            }
        }
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.write(keptDraft("origin-a"))
        val bJob = launch {
            repo.manualCreation.create(draft, binding, "current-b", RecurringPaymentOrigin("rec-1", "2026-08", 5)).getOrThrow()
        }
        entered.await()
        var aAdmission: ManualExpenseCreateAdmission? = null
        val aJob = launch {
            aAdmission = repo.manualCreation.create(
                draft.copy(merchant = "房租"),
                binding,
                "origin-a",
                RecurringPaymentOrigin("rec-1", "2026-08", 7),
            ).getOrThrow()
        }
        yield()
        assertTrue(bJob.isActive)
        assertTrue(aJob.isActive)
        hold.complete(Unit)
        bJob.join()
        aJob.join()
        assertEquals(
            ManualExpenseCreateAdmission.Blocked(RecurringPaymentAdmissionBlock.DifferentGeneration),
            aAdmission,
        )
        assertEquals(1, pendingDao.rows.size)
        assertEquals("expense:local:current-b", pendingDao.rows.values.single().targetId)
        assertEquals("当前草稿", store.read("origin-a")?.note)
    }

    @Test
    fun adoptBindsRawCandidateWhileOffline() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        repo.manualCreation.create(draft, binding, "legacy-ref").getOrThrow()
        val before = pendingDao.rows.values.single().payload
        assertEquals(
            RecurringPaymentOriginAdopt.Bound,
            repo.manualCreation.adoptOrigin(binding, "legacy-ref", "rec-1", "2026-08", 7),
        )
        assertEquals(1, pendingDao.rows.size)
        assertNotEquals(before, pendingDao.rows.values.single().payload)
        assertEquals(
            RecurringPaymentOrigin("rec-1", "2026-08", 7),
            decodeRecurringPaymentOrigin(
                com.ticketbox.OutboxAdapterGraph().recurringPaymentCreateAdapter,
                pendingDao.rows.values.single().payload,
            ),
        )
    }

    @Test
    fun adoptDoesNotRebindAcrossGenerations() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        repo.manualCreation.create(draft, binding, "origin-a", RecurringPaymentOrigin("rec-1", "2026-08", 7)).getOrThrow()
        repo.manualCreation.create(draft, binding, "legacy-b").getOrThrow()
        val aPayload = pendingDao.rows.values.single { it.targetId == "expense:local:origin-a" }.payload
        val rawPayload = pendingDao.rows.values.single { it.targetId == "expense:local:legacy-b" }.payload
        assertEquals(
            RecurringPaymentOriginAdopt.Blocked(RecurringPaymentAdmissionBlock.DifferentGeneration),
            repo.manualCreation.adoptOrigin(binding, "legacy-b", "rec-1", "2026-08", 5),
        )
        assertEquals(aPayload, pendingDao.rows.values.single { it.targetId == "expense:local:origin-a" }.payload)
        assertEquals(rawPayload, pendingDao.rows.values.single { it.targetId == "expense:local:legacy-b" }.payload)
        assertEquals(2, pendingDao.rows.size)
    }

    private fun keptDraft(clientRef: String) = RecurringPaymentDraft(
        clientRef = clientRef,
        amountText = "99.00",
        currencyCode = "JPY",
        merchant = "改过的商户",
        category = "住房",
        note = "当前草稿",
        expenseTime = "2026-08-01T00:00:00Z",
    )
}

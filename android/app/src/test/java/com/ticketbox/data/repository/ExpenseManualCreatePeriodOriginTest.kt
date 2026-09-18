package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

internal class ExpenseManualCreatePeriodOriginTest : ExpensePendingRepositoryOutboxTestBase() {
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
    fun unattributedRawCreateRequiresReviewInsteadOfGuessingMerchant() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        repo.manualCreation.create(draft, binding, "legacy-ref").getOrThrow()
        val origin = RecurringPaymentOrigin("rec-1", "2026-08", occurrenceRowVersion = 7)
        val before = pendingDao.rows.values.single().payload
        val review = repo.manualCreation.create(draft, binding, "fresh-ref", origin).getOrThrow()
            as ManualExpenseCreateAdmission.ReviewRequired
        assertEquals(listOf("legacy-ref"), review.candidateClientRefs)
        assertEquals("新商家", review.candidates.single().request?.merchant)
        assertEquals("legacy-ref", review.candidates.single().request?.clientRef)
        assertEquals(1, pendingDao.rows.size)
        assertEquals(before, pendingDao.rows.values.single().payload)
        assertNull(
            decodeRecurringPaymentOrigin(
                com.ticketbox.OutboxAdapterGraph().recurringPaymentCreateAdapter,
                pendingDao.rows.values.single().payload,
            ),
        )
        assertTrue(repo.manualCreation.observeOrigin(binding, origin).first() is RecurringPaymentOriginLookup.Absent)
        assertEquals(
            RecurringPaymentOriginAdopt.Bound,
            repo.manualCreation.adoptOrigin(
                binding,
                "legacy-ref",
                origin.seriesPublicId,
                origin.period,
                origin.occurrenceRowVersion,
            ),
        )
        val bound = repo.manualCreation.create(draft, binding, "fresh-ref", origin).getOrThrow()
        assertEquals("legacy-ref", (bound as ManualExpenseCreateAdmission.Accepted).clientRef)
        assertEquals(1, pendingDao.rows.size)
        val stored = requireNotNull(
            com.ticketbox.OutboxAdapterGraph().recurringPaymentCreateAdapter.fromJson(
                pendingDao.rows.values.single().payload,
            ),
        )
        assertEquals(7L, stored.occurrenceRowVersion)
        assertEquals("legacy-ref", stored.request.clientRef)
    }

    @Test
    fun confirmingUnattributedRawAllowsANewPeriodCommand() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        repo.manualCreation.create(draft, binding, "legacy-ref").getOrThrow()
        val origin = RecurringPaymentOrigin("rec-1", "2026-08", occurrenceRowVersion = 7)
        val review = repo.manualCreation.create(draft, binding, "fresh-ref", origin).getOrThrow()
            as ManualExpenseCreateAdmission.ReviewRequired
        val before = pendingDao.rows.values.single { it.targetId == "expense:local:legacy-ref" }.payload
        val admitted = repo.manualCreation.create(
            draft,
            binding,
            "fresh-ref",
            origin,
            acknowledgedUnattributed = review.candidateClientRefs,
        ).getOrThrow()
        assertEquals("fresh-ref", (admitted as ManualExpenseCreateAdmission.Accepted).clientRef)
        assertEquals(2, pendingDao.rows.size)
        assertEquals(before, pendingDao.rows.values.single { it.targetId == "expense:local:legacy-ref" }.payload)
        val created = requireNotNull(
            com.ticketbox.OutboxAdapterGraph().recurringPaymentCreateAdapter.fromJson(
                pendingDao.rows.values.single { it.targetId == "expense:local:fresh-ref" }.payload,
            ),
        )
        assertEquals(7L, created.occurrenceRowVersion)
        assertEquals("fresh-ref", created.request.clientRef)
    }

    @Test
    fun readReviewCandidatesMatchesCreateReviewAndDoesNotCreate() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        repo.manualCreation.create(draft, binding, "legacy-ref").getOrThrow()
        val origin = RecurringPaymentOrigin("rec-1", "2026-08", occurrenceRowVersion = 7)
        val review = repo.manualCreation.create(draft, binding, "fresh-ref", origin).getOrThrow()
            as ManualExpenseCreateAdmission.ReviewRequired
        val read = repo.manualCreation.readReviewCandidates(binding).getOrThrow()
        assertEquals(review.candidateClientRefs, read.mapNotNull { it.admittedClientRef() }.distinct().sorted())
        assertEquals("新商家", read.single().request?.merchant)
        assertEquals(1, pendingDao.rows.size)
    }

    @Test
    fun confirmingUnattributedRereviewsWhenTheSeenSetChanges() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        repo.manualCreation.create(draft, binding, "legacy-c").getOrThrow()
        val origin = RecurringPaymentOrigin("rec-1", "2026-08", occurrenceRowVersion = 7)
        val first = repo.manualCreation.create(draft, binding, "fresh-ref", origin).getOrThrow()
            as ManualExpenseCreateAdmission.ReviewRequired
        assertEquals(listOf("legacy-c"), first.candidateClientRefs)
        repo.manualCreation.create(draft, binding, "legacy-d").getOrThrow()
        val again = repo.manualCreation.create(
            draft,
            binding,
            "fresh-ref",
            origin,
            acknowledgedUnattributed = first.candidateClientRefs,
        ).getOrThrow() as ManualExpenseCreateAdmission.ReviewRequired
        assertEquals(listOf("legacy-c", "legacy-d"), again.candidateClientRefs)
        assertEquals(2, pendingDao.rows.size)
        assertTrue(pendingDao.rows.values.none { it.targetId == "expense:local:fresh-ref" })
    }
}
 
package com.ticketbox.data.repository

import androidx.lifecycle.SavedStateHandle
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.ui.navigation.LEGACY_PERIOD_PAYMENT_SESSIONS_KEY
import com.ticketbox.ui.navigation.RecurringPaymentDraftStore
import com.ticketbox.ui.navigation.RecurringPaymentIdentity
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
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
    fun leftoverAdoptOnlyMigratesTheCurrentlyLoadedPeriod() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        repo.manualCreation.create(draft, binding, "august-ref").getOrThrow()
        repo.manualCreation.create(draft, binding, "september-ref").getOrThrow()
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] =
            """[{"binding":{"serverUrl":"${binding.serverUrl}","ledgerId":"${binding.ledgerId}","ownerKey":"${binding.ownerKey}","sessionGeneration":"${binding.sessionGeneration}","bindingRevision":"${binding.bindingRevision}"},"seriesPublicId":"rec-1","period":"2026-08","clientRef":"august-ref","merchant":"新商家","obligationCurrencyCode":"CNY","plannedAmountCents":12345,"ledgerHomeCurrencyCode":"CNY","admitted":false},{"binding":{"serverUrl":"${binding.serverUrl}","ledgerId":"${binding.ledgerId}","ownerKey":"${binding.ownerKey}","sessionGeneration":"${binding.sessionGeneration}","bindingRevision":"${binding.bindingRevision}"},"seriesPublicId":"rec-1","period":"2026-09","clientRef":"september-ref","merchant":"新商家","obligationCurrencyCode":"CNY","plannedAmountCents":12345,"ledgerHomeCurrencyCode":"CNY","admitted":false}]"""
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(
            leftover,
            repo.manualCreation,
            RecurringPaymentIdentity(binding, "rec-1", "2026-09", 3),
        )
        val remaining = leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty()
        assertTrue(remaining.contains("august-ref"))
        assertTrue(!remaining.contains("september-ref"))
        assertEquals("september-ref", store.remembered(binding, "rec-1", "2026-09")?.clientRef)
        assertNull(store.remembered(binding, "rec-1", "2026-08"))
        assertNull(
            decodeRecurringPaymentOrigin(
                com.ticketbox.OutboxAdapterGraph().recurringPaymentCreateAdapter,
                pendingDao.rows.values.single { it.targetId == "expense:local:august-ref" }.payload,
            ),
        )
        val rebuilt = RecurringPaymentDraftStore(SavedStateHandle())
        rebuilt.adoptLegacyPeriodPaymentSessions(
            leftover,
            repo.manualCreation,
            RecurringPaymentIdentity(binding, "rec-1", "2026-08", 7),
        )
        assertNull(leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY])
        assertEquals("august-ref", rebuilt.remembered(binding, "rec-1", "2026-08")?.clientRef)
        val august = RecurringPaymentOrigin("rec-1", "2026-08", 7)
        val found = repo.manualCreation.observeOrigin(binding, august).first()
        assertTrue(found is RecurringPaymentOriginLookup.Found)
        assertEquals("august-ref", found.projection.request?.clientRef)
        val reused = repo.manualCreation.create(draft, binding, "fresh-ref", august).getOrThrow()
        assertEquals("august-ref", (reused as ManualExpenseCreateAdmission.Accepted).clientRef)
        assertEquals(2, pendingDao.rows.size)
    }

    @Test
    fun leftoverAdoptBindsUnwrappedOriginThenRemovesTheKey() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        repo.manualCreation.create(draft, binding, "legacy-ref").getOrThrow()
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] =
            """[{"binding":{"serverUrl":"${binding.serverUrl}","ledgerId":"${binding.ledgerId}","ownerKey":"${binding.ownerKey}","sessionGeneration":"${binding.sessionGeneration}","bindingRevision":"${binding.bindingRevision}"},"seriesPublicId":"rec-1","period":"2026-08","clientRef":"legacy-ref","merchant":"新商家","obligationCurrencyCode":"CNY","plannedAmountCents":12345,"ledgerHomeCurrencyCode":"CNY","category":"住房","note":"自填备注","capturedAmountCents":9800,"admitted":false}]"""
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(
            leftover,
            repo.manualCreation,
            RecurringPaymentIdentity(binding, "rec-1", "2026-08", 7),
        )
        assertNull(leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY])
        assertEquals("legacy-ref", store.remembered(binding, "rec-1", "2026-08")?.clientRef)
        assertEquals(7L, store.remembered(binding, "rec-1", "2026-08")?.occurrenceRowVersion)
        val restored = assertNotNull(store.read("legacy-ref"))
        assertEquals("98.00", restored.amountText)
        assertEquals("住房", restored.category)
        assertEquals("自填备注", restored.note)
        assertEquals("", restored.expenseTime)
        val found = repo.manualCreation.observeOrigin(binding, RecurringPaymentOrigin("rec-1", "2026-08", 7)).first()
        assertTrue(found is RecurringPaymentOriginLookup.Found)
        assertEquals("legacy-ref", found.projection.request?.clientRef)
        assertEquals(1, pendingDao.rows.size)
        val stored = requireNotNull(
            com.ticketbox.OutboxAdapterGraph().recurringPaymentCreateAdapter.fromJson(pendingDao.rows.values.single().payload),
        )
        assertEquals(7L, stored.occurrenceRowVersion)
    }

    @Test
    fun leftoverAdoptUnsubmittedRemembersWithoutCreatingOutbox() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] =
            """[{"binding":{"serverUrl":"${binding.serverUrl}","ledgerId":"${binding.ledgerId}","ownerKey":"${binding.ownerKey}","sessionGeneration":"${binding.sessionGeneration}","bindingRevision":"${binding.bindingRevision}"},"seriesPublicId":"rec-1","period":"2026-08","clientRef":"legacy-ref","merchant":"新商家","obligationCurrencyCode":"CNY","plannedAmountCents":12345,"ledgerHomeCurrencyCode":"CNY","admitted":false}]"""
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(
            leftover,
            repo.manualCreation,
            RecurringPaymentIdentity(binding, "rec-1", "2026-08", 7),
        )
        assertNull(leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY])
        assertEquals("legacy-ref", store.remembered(binding, "rec-1", "2026-08")?.clientRef)
        assertEquals(7L, store.remembered(binding, "rec-1", "2026-08")?.occurrenceRowVersion)
        assertEquals(0, pendingDao.rows.size)
        assertTrue(!store.leftoverUnresolved(leftover, RecurringPaymentIdentity(binding, "rec-1", "2026-08", 7)))
    }

    @Test
    fun leftoverAdoptAdmittedMissingKeepsTheKeyForThatPeriodOnly() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] =
            """[{"binding":{"serverUrl":"${binding.serverUrl}","ledgerId":"${binding.ledgerId}","ownerKey":"${binding.ownerKey}","sessionGeneration":"${binding.sessionGeneration}","bindingRevision":"${binding.bindingRevision}"},"seriesPublicId":"rec-1","period":"2026-08","clientRef":"august-ref","merchant":"新商家","obligationCurrencyCode":"CNY","plannedAmountCents":12345,"ledgerHomeCurrencyCode":"CNY","admitted":true},{"binding":{"serverUrl":"${binding.serverUrl}","ledgerId":"${binding.ledgerId}","ownerKey":"${binding.ownerKey}","sessionGeneration":"${binding.sessionGeneration}","bindingRevision":"${binding.bindingRevision}"},"seriesPublicId":"rec-1","period":"2026-09","clientRef":"september-ref","merchant":"新商家","obligationCurrencyCode":"CNY","plannedAmountCents":12345,"ledgerHomeCurrencyCode":"CNY","admitted":false}]"""
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(
            leftover,
            repo.manualCreation,
            RecurringPaymentIdentity(binding, "rec-1", "2026-09", 3),
        )
        val remaining = leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty()
        assertTrue(remaining.contains("august-ref"))
        assertTrue(!remaining.contains("september-ref"))
        assertNull(store.remembered(binding, "rec-1", "2026-08"))
        assertEquals("september-ref", store.remembered(binding, "rec-1", "2026-09")?.clientRef)
        assertEquals(3L, store.remembered(binding, "rec-1", "2026-09")?.occurrenceRowVersion)
        assertTrue(store.leftoverUnresolved(leftover, RecurringPaymentIdentity(binding, "rec-1", "2026-08", 7)))
        assertTrue(!store.leftoverUnresolved(leftover, RecurringPaymentIdentity(binding, "rec-1", "2026-09", 3)))
        assertEquals(0, pendingDao.rows.size)
        store.retireTask("september-ref")
        assertNull(store.remembered(binding, "rec-1", "2026-09"))
        store.adoptLegacyPeriodPaymentSessions(
            leftover,
            repo.manualCreation,
            RecurringPaymentIdentity(binding, "rec-1", "2026-09", 3),
        )
        assertNull(store.remembered(binding, "rec-1", "2026-09"))
        assertTrue(leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("august-ref"))
        assertTrue(!leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("september-ref"))
    }

    @Test
    fun leftoverIncompleteAugustDoesNotBlockSeptemberUnsubmitted() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] =
            """[{"binding":{"serverUrl":"${binding.serverUrl}","ledgerId":"${binding.ledgerId}","ownerKey":"${binding.ownerKey}","sessionGeneration":"${binding.sessionGeneration}","bindingRevision":"${binding.bindingRevision}"},"seriesPublicId":"rec-1","period":"2026-08","clientRef":"august-ref","merchant":"新商家","obligationCurrencyCode":"CNY","plannedAmountCents":12345,"admitted":false},{"binding":{"serverUrl":"${binding.serverUrl}","ledgerId":"${binding.ledgerId}","ownerKey":"${binding.ownerKey}","sessionGeneration":"${binding.sessionGeneration}","bindingRevision":"${binding.bindingRevision}"},"seriesPublicId":"rec-1","period":"2026-09","clientRef":"september-ref","merchant":"新商家","obligationCurrencyCode":"CNY","plannedAmountCents":12345,"ledgerHomeCurrencyCode":"CNY","admitted":false}]"""
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(
            leftover,
            repo.manualCreation,
            RecurringPaymentIdentity(binding, "rec-1", "2026-09", 3),
        )
        assertEquals("september-ref", store.remembered(binding, "rec-1", "2026-09")?.clientRef)
        assertNull(store.remembered(binding, "rec-1", "2026-08"))
        val remaining = leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty()
        assertTrue(remaining.contains("august-ref"))
        assertTrue(!remaining.contains("september-ref"))
        assertTrue(store.leftoverUnresolved(leftover, RecurringPaymentIdentity(binding, "rec-1", "2026-08", 7)))
        assertTrue(!store.leftoverUnresolved(leftover, RecurringPaymentIdentity(binding, "rec-1", "2026-09", 3)))
        assertEquals(0, pendingDao.rows.size)
    }
}

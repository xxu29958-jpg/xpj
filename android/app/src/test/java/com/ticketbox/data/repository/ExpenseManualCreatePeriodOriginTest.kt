package com.ticketbox.data.repository

import androidx.lifecycle.SavedStateHandle
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.ui.navigation.LEGACY_PERIOD_PAYMENT_SESSIONS_KEY
import com.ticketbox.ui.navigation.RecurringPaymentDraftStore
import com.ticketbox.ui.navigation.RecurringPaymentIdentity
import com.ticketbox.ui.navigation.leftoverPeriodPaymentSessionsJson
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotEquals
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

    @Test
    fun leftoverAdoptOnlyMigratesTheCurrentlyLoadedPeriod() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        repo.manualCreation.create(draft, binding, "august-ref").getOrThrow()
        repo.manualCreation.create(draft, binding, "september-ref").getOrThrow()
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(
            leftoverRow(binding, "2026-08", "august-ref", admitted = false),
            leftoverRow(binding, "2026-09", "september-ref", admitted = false),
        )
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(
            leftover,
            repo.manualCreation,
            RecurringPaymentIdentity(binding, "rec-1", "2026-09", 0),
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
            RecurringPaymentIdentity(binding, "rec-1", "2026-08", 0),
        )
        assertNull(leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY])
        assertEquals("august-ref", rebuilt.remembered(binding, "rec-1", "2026-08")?.clientRef)
        val august = RecurringPaymentOrigin("rec-1", "2026-08", 0)
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
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(
            leftoverRow(binding, "2026-08", "legacy-ref", admitted = false, category = "住房", note = "自填备注", capturedAmountCents = 9800),
        )
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(
            leftover,
            repo.manualCreation,
            RecurringPaymentIdentity(binding, "rec-1", "2026-08", 0),
        )
        assertNull(leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY])
        assertEquals("legacy-ref", store.remembered(binding, "rec-1", "2026-08")?.clientRef)
        assertEquals(0L, store.remembered(binding, "rec-1", "2026-08")?.occurrenceRowVersion)
        val restored = assertNotNull(store.read("legacy-ref"))
        assertEquals("98.00", restored.amountText)
        assertEquals("住房", restored.category)
        assertEquals("自填备注", restored.note)
        assertEquals("", restored.expenseTime)
        val found = repo.manualCreation.observeOrigin(binding, RecurringPaymentOrigin("rec-1", "2026-08", 0)).first()
        assertTrue(found is RecurringPaymentOriginLookup.Found)
        assertEquals("legacy-ref", found.projection.request?.clientRef)
        assertEquals(1, pendingDao.rows.size)
        val stored = requireNotNull(
            com.ticketbox.OutboxAdapterGraph().recurringPaymentCreateAdapter.fromJson(pendingDao.rows.values.single().payload),
        )
        assertEquals(0L, stored.occurrenceRowVersion)
    }

    @Test
    fun leftoverAdoptUnsubmittedRemembersWithoutCreatingOutbox() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(
            leftoverRow(binding, "2026-08", "legacy-ref", admitted = false),
        )
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(
            leftover,
            repo.manualCreation,
            RecurringPaymentIdentity(binding, "rec-1", "2026-08", 0),
        )
        assertNull(leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY])
        assertEquals("legacy-ref", store.remembered(binding, "rec-1", "2026-08")?.clientRef)
        assertEquals(0L, store.remembered(binding, "rec-1", "2026-08")?.occurrenceRowVersion)
        assertEquals(0, pendingDao.rows.size)
        val identity = RecurringPaymentIdentity(binding, "rec-1", "2026-08", 0)
        assertTrue(!store.leftoverUnresolved(leftover, identity))
        assertNull(identity.leftoverSeen(leftover))
    }

    @Test
    fun leftoverAdoptAdmittedMissingKeepsTheKeyForThatPeriodOnly() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(
            leftoverRow(binding, "2026-08", "august-ref", admitted = true),
            leftoverRow(binding, "2026-09", "september-ref", admitted = false),
        )
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(
            leftover,
            repo.manualCreation,
            RecurringPaymentIdentity(binding, "rec-1", "2026-09", 0),
        )
        val remaining = leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty()
        assertTrue(remaining.contains("august-ref"))
        assertTrue(!remaining.contains("september-ref"))
        assertNull(store.remembered(binding, "rec-1", "2026-08"))
        assertEquals("september-ref", store.remembered(binding, "rec-1", "2026-09")?.clientRef)
        assertEquals(0L, store.remembered(binding, "rec-1", "2026-09")?.occurrenceRowVersion)
        assertTrue(store.leftoverUnresolved(leftover, RecurringPaymentIdentity(binding, "rec-1", "2026-08", 7)))
        assertTrue(!store.leftoverUnresolved(leftover, RecurringPaymentIdentity(binding, "rec-1", "2026-09", 3)))
        assertEquals(0, pendingDao.rows.size)
        store.retireTask("september-ref")
        assertNull(store.remembered(binding, "rec-1", "2026-09"))
        store.adoptLegacyPeriodPaymentSessions(
            leftover,
            repo.manualCreation,
            RecurringPaymentIdentity(binding, "rec-1", "2026-09", 0),
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
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(
            leftoverRow(binding, "2026-08", "august-ref", admitted = false, home = null),
            leftoverRow(binding, "2026-09", "september-ref", admitted = false),
        )
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(
            leftover,
            repo.manualCreation,
            RecurringPaymentIdentity(binding, "rec-1", "2026-09", 0),
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

    @Test
    fun leftoverGenerationMoveDoesNotUpgradeUnsubmittedTaskOrDraft() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val identity = RecurringPaymentIdentity(binding, "rec-1", "2026-08", 5)
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(
            leftoverRow(binding, "2026-08", "legacy-ref", admitted = false, category = "住房", note = "旧草稿", capturedAmountCents = 9800),
        )
        leftover[requireNotNull(identity.leftoverSeenKey())] = 2L
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(leftover, repo.manualCreation, identity)
        assertNull(leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY])
        assertNull(store.remembered(binding, "rec-1", "2026-08"))
        assertNull(store.read("legacy-ref"))
        assertNull(identity.leftoverSeen(leftover))
        assertEquals(0, pendingDao.rows.size)
    }

    @Test
    fun leftoverGenerationMoveDoesNotBindRawCreateExpenseAsCurrentOrigin() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        repo.manualCreation.create(draft, binding, "legacy-ref").getOrThrow()
        val before = pendingDao.rows.values.single().payload
        val identity = RecurringPaymentIdentity(binding, "rec-1", "2026-08", 5)
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(
            leftoverRow(binding, "2026-08", "legacy-ref", admitted = false),
        )
        leftover[requireNotNull(identity.leftoverSeenKey())] = 2L
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(leftover, repo.manualCreation, identity)
        assertNull(leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY])
        assertNull(store.remembered(binding, "rec-1", "2026-08"))
        assertNull(identity.leftoverSeen(leftover))
        assertEquals(before, pendingDao.rows.values.single().payload)
        assertNull(
            decodeRecurringPaymentOrigin(
                com.ticketbox.OutboxAdapterGraph().recurringPaymentCreateAdapter,
                pendingDao.rows.values.single().payload,
            ),
        )
        assertTrue(
            repo.manualCreation.observeOrigin(binding, RecurringPaymentOrigin("rec-1", "2026-08", 5)).first()
                is RecurringPaymentOriginLookup.Absent,
        )
        assertEquals(1, pendingDao.rows.size)
    }

    @Test
    fun leftoverSeenFromAnotherBindingRevisionDoesNotRetireTheCurrentMapping() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val first = RecurringPaymentIdentity(binding.copy(bindingRevision = "revision-1"), "rec-1", "2026-09", 5)
        val second = RecurringPaymentIdentity(binding, "rec-1", "2026-09", 5)
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(
            leftoverRow(binding, "2026-09", "legacy-ref", admitted = true),
        )
        leftover[requireNotNull(first.leftoverSeenKey())] = 2L
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(leftover, repo.manualCreation, second)
        assertNotEquals(first.leftoverSeenKey(), second.leftoverSeenKey())
        assertEquals(2L, leftover.get<Long>(requireNotNull(first.leftoverSeenKey())))
        assertNull(second.leftoverSeen(leftover))
        assertTrue(store.leftoverUnresolved(leftover, second))
        assertTrue(leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("legacy-ref"))
        assertNull(store.remembered(second.binding, "rec-1", "2026-09"))
        assertEquals(0, pendingDao.rows.size)
    }

    @Test
    fun leftoverSeenOnTheSameBindingRevisionRetiresWhenGenerationMoves() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val identity = RecurringPaymentIdentity(binding, "rec-1", "2026-09", 5)
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(
            leftoverRow(binding, "2026-09", "legacy-ref", admitted = true),
        )
        leftover[requireNotNull(identity.leftoverSeenKey())] = 2L
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(leftover, repo.manualCreation, identity)
        assertTrue(!store.leftoverUnresolved(leftover, identity))
        assertNull(leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY])
        assertNull(identity.leftoverSeen(leftover))
        assertNull(store.remembered(binding, "rec-1", "2026-09"))
        assertEquals(0, pendingDao.rows.size)
    }

    @Test
    fun leftoverSeenIsNotWrittenWhenThereIsNoMapping() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val identity = RecurringPaymentIdentity(binding, "rec-1", "2026-09", 5)
        val leftover = SavedStateHandle()
        leftover[requireNotNull(identity.leftoverSeenKey())] = 2L
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(leftover, repo.manualCreation, identity)
        assertNull(identity.leftoverSeen(leftover))
        assertTrue(!store.leftoverUnresolved(leftover, identity))
        assertEquals(0, pendingDao.rows.size)
    }

    @Test
    fun leftoverFirstOpenWithoutSeenDoesNotUpgradeUnsubmittedTaskOrDraft() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val identity = RecurringPaymentIdentity(binding, "rec-1", "2026-08", 5)
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(
            leftoverRow(binding, "2026-08", "legacy-ref", admitted = false, category = "住房", note = "旧草稿", capturedAmountCents = 9800),
        )
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(leftover, repo.manualCreation, identity)
        assertTrue(store.leftoverUnresolved(leftover, identity))
        assertNull(store.remembered(binding, "rec-1", "2026-08"))
        assertNull(store.read("legacy-ref"))
        assertNull(identity.leftoverSeen(leftover))
        assertEquals(0, pendingDao.rows.size)
    }

    @Test
    fun leftoverFirstOpenWithoutSeenDoesNotBindRawCreateExpense() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        repo.manualCreation.create(draft, binding, "legacy-ref").getOrThrow()
        val before = pendingDao.rows.values.single().payload
        val identity = RecurringPaymentIdentity(binding, "rec-1", "2026-08", 5)
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(
            leftoverRow(binding, "2026-08", "legacy-ref", admitted = false),
        )
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(leftover, repo.manualCreation, identity)
        assertTrue(store.leftoverUnresolved(leftover, identity))
        assertNull(store.remembered(binding, "rec-1", "2026-08"))
        assertNull(identity.leftoverSeen(leftover))
        assertEquals(before, pendingDao.rows.values.single().payload)
        assertNull(
            decodeRecurringPaymentOrigin(
                com.ticketbox.OutboxAdapterGraph().recurringPaymentCreateAdapter,
                pendingDao.rows.values.single().payload,
            ),
        )
        assertTrue(
            repo.manualCreation.observeOrigin(binding, RecurringPaymentOrigin("rec-1", "2026-08", 5)).first()
                is RecurringPaymentOriginLookup.Absent,
        )
        assertEquals(1, pendingDao.rows.size)
    }

    private fun leftoverRow(
        binding: LogicalSessionBinding,
        period: String,
        clientRef: String,
        admitted: Boolean,
        home: String? = "CNY",
        category: String? = null,
        note: String? = null,
        capturedAmountCents: Long? = null,
    ) = LegacyPeriodPaymentSession(
        binding, "rec-1", period, clientRef, "新商家", "CNY", 12_345, home, category, note, capturedAmountCents, admitted,
    )
}

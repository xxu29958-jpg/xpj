package com.ticketbox.data.repository

import androidx.lifecycle.SavedStateHandle
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.ui.navigation.LEGACY_PERIOD_PAYMENT_SESSIONS_KEY
import com.ticketbox.ui.navigation.LegacyCompatibilityState
import com.ticketbox.ui.navigation.LegacyContinueResult
import com.ticketbox.ui.navigation.RecurringPaymentDraft
import com.ticketbox.ui.navigation.RecurringPaymentDraftStore
import com.ticketbox.ui.navigation.RecurringPaymentIdentity
import com.ticketbox.ui.navigation.leftoverPeriodPaymentSessionsJson
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

internal class ExpenseManualCreateLeftoverContinueTest : ExpensePendingRepositoryOutboxTestBase() {
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
    @Test
    fun leftoverContinueOpensDraftWithoutRetiringLegacyEvidence() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        repo.manualCreation.create(draft, binding, "legacy-ref").getOrThrow()
        val before = pendingDao.rows.values.single().payload
        val identity = RecurringPaymentIdentity(binding, "rec-1", "2026-08", 5)
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(
            leftoverRow(binding, "2026-08", "legacy-ref", admitted = false, category = "住房", note = "旧草稿", capturedAmountCents = 9800),
        )
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(leftover, repo.manualCreation, identity)
        val opened = identity.leftoverInspectContinue(store.legacyPeriodPaymentSessions(leftover)) {
            repo.manualCreation.inspectOrigin(binding, RecurringPaymentOrigin("rec-1", "2026-08", 5))
        } as LegacyContinueResult.Opened
        opened.continuation.draft?.let(store::write)
        assertTrue(leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("legacy-ref"))
        assertNull(store.remembered(binding, "rec-1", "2026-08"))
        assertEquals("住房", store.read("legacy-ref")?.category)
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
        assertNull(identity.leftoverSeen(leftover))
        assertEquals("legacy-ref", opened.continuation.task.clientRef)
    }

    @Test
    fun leftoverContinueDoesNotOpenWhenActiveOriginAlreadyExists() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        repo.manualCreation.create(draft, binding, "origin-a", RecurringPaymentOrigin("rec-1", "2026-08", 5)).getOrThrow()
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(
            leftoverRow(binding, "2026-08", "legacy-b", admitted = false, category = "住房", note = "旧草稿", capturedAmountCents = 9800),
        )
        val identity = RecurringPaymentIdentity(binding, "rec-1", "2026-08", 5)
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.write(
            RecurringPaymentDraft("legacy-b", "98.00", "CNY", "新商家", "住房", "旧草稿", ""),
        )
        store.adoptLegacyPeriodPaymentSessions(leftover, repo.manualCreation, identity)
        assertTrue(store.leftoverUnresolved(leftover, identity))
        assertEquals(
            LegacyContinueResult.ExistingOrigin,
            identity.leftoverInspectContinue(store.legacyPeriodPaymentSessions(leftover)) {
                repo.manualCreation.inspectOrigin(binding, RecurringPaymentOrigin("rec-1", "2026-08", 5))
            },
        )
        assertTrue(leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("legacy-b"))
        assertNull(store.remembered(binding, "rec-1", "2026-08"))
        assertEquals("住房", store.read("legacy-b")?.category)
        val found = repo.manualCreation.observeOrigin(binding, RecurringPaymentOrigin("rec-1", "2026-08", 5)).first()
        assertTrue(found is RecurringPaymentOriginLookup.Found)
        assertEquals("origin-a", found.projection.request?.clientRef)
        assertEquals(1, pendingDao.rows.size)
    }

    @Test
    fun leftoverContinueKeepsEvidenceWhenOriginAppearsAfterAbsentInspect() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(
            leftoverRow(binding, "2026-08", "legacy-b", admitted = false, category = "住房", note = "旧草稿", capturedAmountCents = 9800),
        )
        val identity = RecurringPaymentIdentity(binding, "rec-1", "2026-08", 5)
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(leftover, repo.manualCreation, identity)
        val released = CompletableDeferred<Unit>()
        val opened = CompletableDeferred<LegacyContinueResult>()
        backgroundScope.launch {
            opened.complete(
                identity.leftoverInspectContinue(store.legacyPeriodPaymentSessions(leftover)) {
                    val lookup = repo.manualCreation.inspectOrigin(
                        binding,
                        RecurringPaymentOrigin("rec-1", "2026-08", 5),
                    )
                    released.complete(Unit)
                    lookup
                },
            )
        }
        released.await()
        repo.manualCreation.create(draft, binding, "origin-a", RecurringPaymentOrigin("rec-1", "2026-08", 5)).getOrThrow()
        val result = opened.await() as LegacyContinueResult.Opened
        result.continuation.draft?.let(store::write)
        assertEquals("legacy-b", result.continuation.task.clientRef)
        assertTrue(leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("legacy-b"))
        assertEquals("住房", store.read("legacy-b")?.category)
        assertNull(store.remembered(binding, "rec-1", "2026-08"))
        assertEquals(1, pendingDao.rows.size)
        val found = repo.manualCreation.observeOrigin(binding, RecurringPaymentOrigin("rec-1", "2026-08", 5)).first()
        assertTrue(found is RecurringPaymentOriginLookup.Found)
        assertEquals("origin-a", found.projection.request?.clientRef)
    }

    @Test
    fun leftoverContinueKeepsEvidenceWhenOriginAppearsAfterDraftOpened() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(
            leftoverRow(binding, "2026-08", "legacy-b", admitted = false, category = "住房", note = "旧草稿", capturedAmountCents = 9800),
        )
        val identity = RecurringPaymentIdentity(binding, "rec-1", "2026-08", 5)
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(leftover, repo.manualCreation, identity)
        val opened = identity.leftoverInspectContinue(store.legacyPeriodPaymentSessions(leftover)) {
            repo.manualCreation.inspectOrigin(binding, RecurringPaymentOrigin("rec-1", "2026-08", 5))
        } as LegacyContinueResult.Opened
        opened.continuation.draft?.let(store::write)
        store.write(requireNotNull(store.read("legacy-b")).copy(note = "已改"))
        repo.manualCreation.create(draft, binding, "origin-a", RecurringPaymentOrigin("rec-1", "2026-08", 5)).getOrThrow()
        assertTrue(leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("legacy-b"))
        assertEquals("已改", store.read("legacy-b")?.note)
        assertNull(store.remembered(binding, "rec-1", "2026-08"))
        val found = repo.manualCreation.observeOrigin(binding, RecurringPaymentOrigin("rec-1", "2026-08", 5)).first()
        assertTrue(found is RecurringPaymentOriginLookup.Found)
        assertEquals("origin-a", found.projection.request?.clientRef)
        assertEquals(1, pendingDao.rows.size)
    }

    @Test
    fun leftoverContinueAfterFailedHandoffOpensWithoutStickyFailure() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(
            leftoverRow(binding, "2026-08", "legacy-ref", admitted = false, category = "住房", note = "旧草稿", capturedAmountCents = 9800),
        )
        val identity = RecurringPaymentIdentity(binding, "rec-1", "2026-08", 5)
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        val sessions = store.legacyPeriodPaymentSessions(leftover)
        val failed = identity.leftoverState(sessions, unresolved = true, remembered = null, error = "adoptOrigin failed")
        val held = failed as LegacyCompatibilityState.Held
        assertEquals("adoptOrigin failed", held.error)
        assertEquals("legacy-ref", held.continuation?.task?.clientRef)
        val opened = identity.leftoverInspectContinue(sessions) {
            repo.manualCreation.inspectOrigin(binding, RecurringPaymentOrigin("rec-1", "2026-08", 5))
        } as LegacyContinueResult.Opened
        opened.continuation.draft?.let(store::write)
        val recovered = identity.leftoverState(store.legacyPeriodPaymentSessions(leftover), unresolved = true, remembered = null) as LegacyCompatibilityState.Held
        assertNull(recovered.error)
        assertTrue(leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("legacy-ref"))
        assertNull(store.remembered(binding, "rec-1", "2026-08"))
        assertEquals("住房", store.read("legacy-ref")?.category)
    }

    @Test
    fun leftoverAbandonAfterFailedHandoffClearsMappingAndUnblocks() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(
            leftoverRow(binding, "2026-08", "legacy-ref", admitted = false),
        )
        val identity = RecurringPaymentIdentity(binding, "rec-1", "2026-08", 5)
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        val failed = identity.leftoverState(
            store.legacyPeriodPaymentSessions(leftover),
            unresolved = true,
            remembered = null,
            error = "handoff failed",
        )
        assertTrue(failed is LegacyCompatibilityState.Held)
        store.retireFulfilledLegacySessions(leftover, identity, dropUnreadable = true)
        val ready = identity.leftoverState(
            store.legacyPeriodPaymentSessions(leftover),
            unresolved = store.leftoverUnresolved(leftover, identity),
            remembered = store.remembered(binding, "rec-1", "2026-08"),
        )
        assertTrue(ready is LegacyCompatibilityState.Ready)
        assertNull(leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY])
        assertNull(store.remembered(binding, "rec-1", "2026-08"))
    }

    @Test
    fun leftoverAcceptedBRetiresExactMappingAndDraft() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(
            leftoverRow(binding, "2026-08", "legacy-b", admitted = false, category = "住房", note = "旧草稿", capturedAmountCents = 9800),
        )
        val identity = RecurringPaymentIdentity(binding, "rec-1", "2026-08", 5)
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(leftover, repo.manualCreation, identity)
        store.write(RecurringPaymentDraft("legacy-b", "98.00", "CNY", "新商家", "住房", "旧草稿", ""))
        val admitted = repo.manualCreation.create(
            draft,
            binding,
            "legacy-b",
            RecurringPaymentOrigin("rec-1", "2026-08", 5),
        ).getOrThrow() as ManualExpenseCreateAdmission.Accepted
        assertEquals("legacy-b", admitted.clientRef)
        val found = repo.manualCreation.observeOrigin(binding, RecurringPaymentOrigin("rec-1", "2026-08", 5)).first()
        assertTrue(found is RecurringPaymentOriginLookup.Found)
        assertEquals("legacy-b", found.projection.request?.clientRef)
        store.retireFulfilledLegacySessions(leftover, identity)
        store.removeDraft("legacy-b")
        assertNull(leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY])
        assertNull(store.read("legacy-b"))
        assertEquals(1, pendingDao.rows.size)
    }

    @Test
    fun leftoverAcceptedAKeepsUnsubmittedBDraftAndMapping() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(
            leftoverRow(binding, "2026-08", "legacy-b", admitted = false, category = "住房", note = "旧草稿", capturedAmountCents = 9800),
        )
        val identity = RecurringPaymentIdentity(binding, "rec-1", "2026-08", 5)
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(leftover, repo.manualCreation, identity)
        store.write(RecurringPaymentDraft("legacy-b", "98.00", "CNY", "新商家", "住房", "旧草稿", ""))
        repo.manualCreation.create(draft, binding, "origin-a", RecurringPaymentOrigin("rec-1", "2026-08", 5)).getOrThrow()
        val admitted = repo.manualCreation.create(
            draft,
            binding,
            "legacy-b",
            RecurringPaymentOrigin("rec-1", "2026-08", 5),
        ).getOrThrow() as ManualExpenseCreateAdmission.Accepted
        assertEquals("origin-a", admitted.clientRef)
        assertTrue(leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("legacy-b"))
        assertEquals("住房", store.read("legacy-b")?.category)
        val found = repo.manualCreation.observeOrigin(binding, RecurringPaymentOrigin("rec-1", "2026-08", 5)).first()
        assertTrue(found is RecurringPaymentOriginLookup.Found)
        assertEquals("origin-a", found.projection.request?.clientRef)
        assertEquals(1, pendingDao.rows.size)
    }

    @Test
    fun leftoverInspectContinueIsIdempotentAndDoesNotHalfDelete() = runTest {
        val pendingDao = FakePendingMutationDao()
        val repo = createRepo(FakeExpenseDao(), outbox(pendingDao))
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val leftover = SavedStateHandle()
        leftover[LEGACY_PERIOD_PAYMENT_SESSIONS_KEY] = leftoverPeriodPaymentSessionsJson(
            leftoverRow(binding, "2026-08", "legacy-b", admitted = false, category = "住房", note = "旧草稿", capturedAmountCents = 9800),
        )
        val identity = RecurringPaymentIdentity(binding, "rec-1", "2026-08", 5)
        val store = RecurringPaymentDraftStore(SavedStateHandle())
        store.adoptLegacyPeriodPaymentSessions(leftover, repo.manualCreation, identity)
        repeat(2) {
            val result = identity.leftoverInspectContinue(store.legacyPeriodPaymentSessions(leftover)) {
                repo.manualCreation.inspectOrigin(binding, RecurringPaymentOrigin("rec-1", "2026-08", 5))
            } as LegacyContinueResult.Opened
            result.continuation.draft?.let(store::write)
        }
        assertTrue(leftover.get<String>(LEGACY_PERIOD_PAYMENT_SESSIONS_KEY).orEmpty().contains("legacy-b"))
        assertEquals("住房", store.read("legacy-b")?.category)
        assertNull(store.remembered(binding, "rec-1", "2026-08"))
        assertEquals(0, pendingDao.rows.size)
    }
}

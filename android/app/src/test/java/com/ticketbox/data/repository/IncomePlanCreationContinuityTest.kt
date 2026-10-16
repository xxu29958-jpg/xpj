package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.IncomePlanCreateRequestDto
import com.ticketbox.data.remote.dto.IncomePlanDto
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomeSourceType
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class IncomePlanCreationContinuityTest {
    @Test fun mismatchedReceiptAndUnknownOriginalNeverBecomeDone() = runTest {
        val f = IncomeCreationFixture()
        val id = f.repository.create(f.binding, f.draft, f.creationKey).getOrThrow()
        f.latest = f.latest.copy(homeCurrencyCode = "CNY")
        f.dao.runnableBatches += listOf(id)
        assertEquals(1, f.engine().drainOnce().failures)
        assertFalse(f.pending(id).canRetry)
        val row = f.pending(id).row
        val dispatcher = f.dispatcher()
        assertTrue(dispatcher.dispatch(row.copy(payloadJson = row.payloadJson.replace("\"JPY\"", "null"))) is DispatchResult.Failure)
        assertTrue(dispatcher.dispatch(row.copy(targetId = "income_plan_create:other")) is DispatchResult.Failure)
        assertEquals(1, f.keys.size)
    }

    @Test fun originalRecoveryRejectsForeignOriginBindingAndReadonlyRetry() = runTest {
        val f = IncomeCreationFixture()
        val id = f.repository.create(f.binding, f.draft, f.creationKey).getOrThrow()
        f.outbox.markFailed(id, "client_upgrade_required")
        val original = f.pending(id)
        assertEquals(null, f.repository.describeSubmission(original.row.copy(serverUrl = "https://foreign.example")))
        f.session.switchLedgerForFixture("other", "其它账本")
        assertTrue(f.repository.create(f.binding, f.draft, f.creationKey).isFailure)
        assertTrue(f.repository.recoverSubmission(f.binding, original, false).isFailure)
        f.session.switchLedgerForFixture("owner", "原账本", "viewer")
        val binding = f.repository.observeActiveLedgerAccess().first()!!.binding
        assertTrue(f.repository.recoverSubmission(binding, original, false).isFailure)
        f.repository.recoverSubmission(binding, original, true).getOrThrow()
        assertTrue(f.keys.isEmpty())
    }

    @Test fun missingReceiptKeepsTheOriginalRowForReviewWithoutClaimingAcceptance() = runTest {
        val f = IncomeCreationFixture()
        val id = f.repository.create(f.binding, f.draft, f.creationKey).getOrThrow()
        val original = f.dao.rows.getValue(id)
        f.outbox.markDone(id, receiptJson = "{}")
        val pending = f.pending(id)
        assertFalse(pending.isConfirmed)
        assertTrue(pending.requiresReview)
        assertTrue(pending.canDrop)
        assertEquals(null, pending.confirmed)
        assertEquals(original.payload, f.dao.rows.getValue(id).payload)
        assertEquals(original.idempotencyKey, pending.row.idempotencyKey)
    }

    @Test fun originalLookupRejectsForeignStoredOriginButAllowsReadonlyReview() = runTest {
        val f = IncomeCreationFixture()
        val id = f.repository.create(f.binding, f.draft, f.creationKey).getOrThrow()
        val original = f.dao.rows.getValue(id)
        for (foreign in listOf(original.copy(serverUrl = "https://foreign.example"),
            original.copy(payload = original.payload.replace(f.binding.sessionGeneration, "foreign-session")),
            original.copy(payload = original.payload.replace(f.binding.bindingRevision, "foreign-binding")))) {
            f.dao.rows[id] = foreign
            assertTrue(f.repository.originalCreation(f.binding, f.creationKey).isFailure)
            assertTrue(f.repository.create(f.binding, f.draft, f.creationKey).isFailure)
            assertEquals(1, f.dao.rows.size)
        }
        f.dao.rows[id] = original
        val current = requireNotNull(f.session.sessionStore.currentSession())
        f.session.sessionStore.replaceForFixture(current.copy(identity = current.identity.copy(role = "viewer")))
        val readonly = requireNotNull(f.repository.observeActiveLedgerAccess().first()).binding
        assertEquals(id, f.repository.originalCreation(readonly, f.creationKey).getOrThrow()?.row?.id)
        assertTrue(f.repository.create(readonly, f.draft, f.creationKey).isFailure)
        assertTrue(f.repository.originalCreation(readonly.copy(ownerKey = "foreign-owner"), f.creationKey).isFailure)
    }
}

internal class IncomeCreationFixture {
    val session = TestSessionFixture().apply { saveToken("synthetic-income-session") }
    val adapters = OutboxAdapterGraph()
    val dao = FakePendingMutationDao()
    val outbox = testOutboxRepository(dao)
    val draft = IncomePlanDraft("2026-09", "JPY", "旅行补贴", IncomeSourceType.OTHER,
        IncomeFrequency.ONE_TIME, "2026-09", 1200, 10)
    val creationKey = "original-income-creation"
    var latest = IncomePlanDto("income-created", "旅行补贴", "other", "one_time", "2026-09", 1200, 10,
        "active", "2026-09-09T00:00:00Z", "2026-09-09T00:00:00Z", 1, null, "JPY")
    val keys = mutableListOf<String>()
    val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
        override suspend fun createIncomePlan(request: IncomePlanCreateRequestDto, idempotencyKey: String): IncomePlanDto {
            keys += idempotencyKey
            assertEquals(draft.toCreateRequest(), request)
            return latest
        }
    }
    private val provider = testApiServiceProvider(object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
    }, session)
    val binding = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
    val repository = testIncomePlanRepository(provider, outbox, adapters.incomePlanSubmissionAdapter, adapters.incomePlanReceiptAdapter)
    suspend fun pending(id: Long) = repository.observeSubmissions(binding).first().single { it.row.id == id }
    fun dispatcher() = IncomePlanDispatcher(PendingMutationType.CreateIncomePlan, { api },
        adapters.incomePlanSubmissionAdapter, adapters.incomePlanReceiptAdapter)
    fun engine() = OutboxDrainEngine(outbox, listOf(dispatcher()), maxAttempts = 1)
}

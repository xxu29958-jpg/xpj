package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.IncomePlanCreateRequestDto
import com.ticketbox.data.remote.dto.IncomePlanDto
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomeSourceType
import java.io.IOException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class IncomePlanCreationContinuityTest {
    @Test fun durableCreateReplaysOriginalCurrencyMonthAndReceiptAfterLostAck() = runTest {
        val f = IncomeCreationFixture()
        val id = f.repository.create(f.binding, f.draft).getOrThrow()
        val original = f.dao.rows.getValue(id)
        assertTrue(f.keys.isEmpty())
        assertEquals("JPY", f.pending(id).intent?.homeCurrencyCode)
        assertEquals("2026-09", f.pending(id).intent?.request?.intentMonth)
        assertEquals(1, f.engine().drainOnce().failures)
        f.latest = f.latest.copy(amountCents = 9999, status = "archived", rowVersion = 3)
        f.repository.recoverSubmission(f.binding, f.pending(id), false).getOrThrow()
        f.loseAck = false
        assertEquals(1, f.engine().drainOnce().done)
        assertEquals(listOf(original.idempotencyKey, original.idempotencyKey), f.keys)
        assertEquals(original.payload, f.dao.rows.getValue(id).payload)
        assertEquals(1200L, f.pending(id).confirmed?.amountCents)
        assertEquals(1, f.receipts.size)
    }

    @Test fun mismatchedReceiptAndUnknownOriginalNeverBecomeDone() = runTest {
        val f = IncomeCreationFixture()
        val id = f.repository.create(f.binding, f.draft).getOrThrow()
        f.loseAck = false
        f.latest = f.latest.copy(homeCurrencyCode = "CNY")
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
        val id = f.repository.create(f.binding, f.draft).getOrThrow()
        f.outbox.markFailed(id, "client_upgrade_required")
        val original = f.pending(id)
        assertEquals(null, f.repository.describeSubmission(original.row.copy(serverUrl = "https://foreign.example")))
        f.session.switchLedgerForFixture("other", "其它账本")
        assertTrue(f.repository.create(f.binding, f.draft).isFailure)
        assertTrue(f.repository.recoverSubmission(f.binding, original, false).isFailure)
        f.session.switchLedgerForFixture("owner", "原账本", "viewer")
        val binding = f.repository.observeActiveLedgerAccess().first()!!.binding
        assertTrue(f.repository.recoverSubmission(binding, original, false).isFailure)
        f.repository.recoverSubmission(binding, original, true).getOrThrow()
        assertTrue(f.keys.isEmpty())
    }

    @Test fun missingReceiptKeepsTheOriginalRowForReviewWithoutClaimingAcceptance() = runTest {
        val f = IncomeCreationFixture()
        val id = f.repository.create(f.binding, f.draft).getOrThrow()
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
}

internal class IncomeCreationFixture {
    val session = TestSessionFixture().apply { saveToken("synthetic-income-session") }
    val adapters = OutboxAdapterGraph()
    val dao = FakePendingMutationDao()
    val outbox = testOutboxRepository(dao)
    val draft = IncomePlanDraft("2026-09", "JPY", "旅行补贴", IncomeSourceType.OTHER,
        IncomeFrequency.ONE_TIME, "2026-09", 1200, 10)
    var latest = IncomePlanDto("income-created", "旅行补贴", "other", "one_time", "2026-09", 1200, 10,
        "active", "2026-09-09T00:00:00Z", "2026-09-09T00:00:00Z", 1, null, "JPY")
    var loseAck = true
    val keys = mutableListOf<String>()
    val receipts = mutableMapOf<String, IncomePlanDto>()
    val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
        override suspend fun createIncomePlan(request: IncomePlanCreateRequestDto, idempotencyKey: String): IncomePlanDto {
            keys += idempotencyKey
            assertEquals(draft.toCreateRequest(), request)
            val receipt = receipts.getOrPut(idempotencyKey) { latest }
            if (loseAck) throw IOException("Synthetic lost acknowledgement")
            return receipt
        }
    }
    private val provider = testApiServiceProvider(object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
    }, session)
    val binding = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
    val repository = IncomePlanRepository(provider, outbox, adapters.incomePlanSubmissionAdapter, adapters.incomePlanReceiptAdapter)
    suspend fun pending(id: Long) = repository.observeSubmissions(binding).first().single { it.row.id == id }
    fun dispatcher() = IncomePlanDispatcher(PendingMutationType.CreateIncomePlan, { api },
        adapters.incomePlanSubmissionAdapter, adapters.incomePlanReceiptAdapter)
    fun engine() = OutboxDrainEngine(outbox, listOf(dispatcher()), maxAttempts = 1)
}

package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
import com.ticketbox.data.remote.dto.RecurringOccurrencePaymentRequestDto
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class RecurringOccurrenceRepositoryTest {
    @Test
    fun unrelatedReceiptCannotSettleTheOriginalAssociation() = runTest {
        val fixture = OccurrenceFixture()
        fixture.api.returnAnotherPeriod = true
        val id = fixture.repository.enqueue(fixture.binding, fixture.draft).getOrThrow()
        val original = fixture.dao.rows.getValue(id)
        fixture.dao.runnableBatches += listOf(id)
        assertEquals(1, fixture.engine(fixture.outbox, fixture.clock).drainOnce().failures)
        val retained = fixture.dao.rows.getValue(id)
        assertEquals(PendingMutationStatus.Failed.wireValue, retained.status)
        assertEquals(original.payload, retained.payload)
        assertEquals(original.idempotencyKey, retained.idempotencyKey)
    }

    @Test
    fun unknownPayloadRemainsVisibleAndMissingActionCannotBecomeClear() = runTest {
        val fixture = OccurrenceFixture()
        val id = fixture.repository.enqueue(fixture.binding, fixture.draft).getOrThrow()
        val original = fixture.dao.rows.getValue(id)
        val payload = requireNotNull(fixture.adapter.readSupportedOccurrence(original.payload))
        assertNull(fixture.adapter.readSupportedOccurrence(original.payload.replace("\"action\":\"link\",", "")))
        val unknown = original.copy(payload = fixture.adapter.toJson(payload.copy(revision = 99)))
        fixture.dao.rows[id] = unknown
        fixture.dao.runnableBatches += listOf(id)
        fixture.engine(fixture.outbox, fixture.clock).drainOnce()
        assertTrue(fixture.api.calls.isEmpty())
        val retained = fixture.dao.rows.getValue(id)
        assertEquals(PendingMutationStatus.Failed.wireValue, retained.status)
        assertEquals(unknown.payload, retained.payload)
        assertEquals(original.idempotencyKey, retained.idempotencyKey)
    }

    @Test
    fun readonlyAndChangedBindingCannotPublishAnAssociation() = runTest {
        val viewer = OccurrenceFixture("viewer")
        assertTrue(viewer.repository.enqueue(viewer.binding, viewer.draft).isFailure)
        assertTrue(viewer.dao.rows.isEmpty())
        val changed = OccurrenceFixture()
        changed.session.switchLedgerForFixture("other", "另一账本")
        assertTrue(changed.repository.enqueue(changed.binding, changed.draft).isFailure)
        assertTrue(changed.dao.rows.isEmpty())
    }

    @Test
    fun protocolRefusalsCanResumeButUnknownRefusalsRequireReview() = runTest {
        for (code in listOf("runtime_version_mismatch", "client_upgrade_required", "future_write_refusal")) {
            val fixture = OccurrenceFixture()
            val id = fixture.repository.enqueue(fixture.binding, fixture.draft).getOrThrow()
            val original = fixture.dao.rows.getValue(id)
            fixture.api.refusalCode = code
            fixture.dao.runnableBatches += listOf(id)
            assertEquals(1, fixture.engine(fixture.outbox, fixture.clock).drainOnce().failures)
            val retained = fixture.dao.rows.getValue(id)
            assertEquals(PendingMutationStatus.Failed.wireValue, retained.status)
            assertEquals(original.payload, retained.payload)
            assertEquals(original.idempotencyKey, retained.idempotencyKey)
            val pending = requireNotNull(fixture.repository.describe(retained.toDomain()))
            if (code == "future_write_refusal") {
                assertFalse(pending.canRetry)
                assertTrue(fixture.repository.recover(fixture.binding, retained.toDomain(), drop = false).isFailure)
                assertEquals(retained, fixture.dao.rows.getValue(id))
                continue
            }
            assertTrue(pending.canRetry)
            fixture.api.refusalCode = null
            fixture.repository.recover(fixture.binding, retained.toDomain(), drop = false).getOrThrow()
            fixture.dao.runnableBatches += listOf(id)
            assertEquals(1, fixture.engine(fixture.outbox, fixture.clock).drainOnce().done)
            assertEquals(fixture.api.calls.first(), fixture.api.calls.last())
        }
    }

    @Test
    fun legacyDisplayCurrencyIsUnknownWhileTheOriginalAssociationCanStillResume() = runTest {
        val fixture = OccurrenceFixture()
        val id = fixture.repository.enqueue(fixture.binding, fixture.draft).getOrThrow()
        val legacy = """{"revision":1,"seriesPublicId":"recurring-1","seriesLabel":"房租","period":"2026-09",
            "homeCurrencyCode":"CNY","originSessionGeneration":"old-session","originBindingRevision":"old-binding",
            "paymentLabel":"房租付款","paymentAmountCents":1200,
            "request":{"action":"link","expected_row_version":0,"expected_series_row_version":7,
            "expense_public_id":"payment-1","expected_expense_row_version":3}}"""
        val original = fixture.dao.rows.getValue(id).copy(payload = legacy,
            status = PendingMutationStatus.Failed.wireValue, lastError = "client_upgrade_required")
        fixture.dao.rows[id] = original
        val pending = requireNotNull(fixture.repository.describe(original.toDomain()))
        assertEquals(1200L, pending.intent?.paymentAmountCents)
        assertNull(pending.intent?.paymentCurrencyCode)
        assertTrue(pending.canRetry)
        assertNull(fixture.repository.describe(original.toDomain().copy(serverUrl = "https://another.example.test")))
        fixture.repository.recover(fixture.binding, original.toDomain(), drop = false).getOrThrow()
        assertEquals(legacy, fixture.dao.rows.getValue(id).payload)
        fixture.dao.runnableBatches += listOf(id)
        assertEquals(1, fixture.engine(fixture.outbox, fixture.clock).drainOnce().done)
        assertEquals(original.idempotencyKey, fixture.api.calls.single().second)
        assertEquals(pending.intent?.request, fixture.api.calls.single().first)
    }
}

private class OccurrenceFixture(role: String = "owner") {
    val session = TestSessionFixture().apply {
        saveToken("synthetic-session")
        if (role != "owner") switchLedgerForFixture("owner", "测试账本", role)
    }
    val api = OccurrenceApiProbe()
    val provider = testApiServiceProvider(object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
    }, session)
    val binding = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
    val dao = FakePendingMutationDao()
    val clock: Clock = Clock.fixed(Instant.parse("2026-09-06T00:00:00Z"), ZoneOffset.UTC)
    val outbox = OutboxRepository(onRowsDeleted = {}, dao = dao, clock = clock,
        bindingProvider = { provider.currentSession().toOutboxBinding() })
    val adapter = OutboxAdapterGraph().recurring.recurringOccurrenceAdapter
    private val readCache = FakeExpenseDao()
    val repository = RecurringOccurrenceRepository(provider, outbox, adapter,
        RecurringQueryReader(provider, readCache, testSnapshotCoordinator(provider, outbox, readCache)))
    val draft = OccurrencePaymentDraft(occurrenceFixture(), "房租",
        RecurringOccurrencePaymentRequestDto("link", 0, 7, "payment-1", 3), "房租付款", 10_000, "CNY")

    fun engine(outbox: OutboxRepository, clock: Clock) = OutboxDrainEngine(outbox,
        listOf(RecurringOccurrenceDispatcher({ api }, adapter)), now = clock::millis)
}

private class OccurrenceApiProbe : ApiService by FakeApiService(mutableListOf(), 0) {
    val calls = mutableListOf<Pair<RecurringOccurrencePaymentRequestDto, String>>()
    private val reply = occurrenceFixture().copy(rowVersion = 1, state = "fulfilled", reservedAmountCents = 0,
        expensePublicId = "payment-1", paidAmountCents = 10_000, nextDueDate = "2026-10-05")
    var refusalCode: String? = null
    var returnAnotherPeriod = false

    override suspend fun setRecurringOccurrencePayment(
        publicId: String, month: String, request: RecurringOccurrencePaymentRequestDto, idempotencyKey: String,
    ): RecurringOccurrenceDto {
        assertEquals("recurring-1", publicId)
        assertEquals("2026-09", month)
        calls += request to idempotencyKey
        refusalCode?.let { code ->
            throw HttpException(Response.error<Any>(409,
                """{"error":"$code","message":"请更新配套版本后重试。"}""".toResponseBody("application/json".toMediaType())))
        }
        return if (returnAnotherPeriod) reply.copy(period = "2026-08") else reply
    }
}

private fun occurrenceFixture() = RecurringOccurrenceDto("recurring-1", "2026-09", 7, 0, "unfulfilled",
    10_000, 10_000, null, null, "2026-09-05")

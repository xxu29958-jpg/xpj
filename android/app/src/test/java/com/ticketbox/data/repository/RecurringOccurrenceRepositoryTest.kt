package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
import com.ticketbox.data.remote.dto.RecurringOccurrencePaymentRequestDto
import com.ticketbox.domain.model.CurrencyCode
import java.io.IOException
import java.time.Clock
import java.time.Duration
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class RecurringOccurrenceRepositoryTest {
    @Test
    fun acceptancePrecedesDispatchAndRestartReplaysOriginalKeyAndAllVersions() = runTest {
        val fixture = OccurrenceFixture()
        val id = fixture.repository.enqueue(fixture.binding, fixture.draft).getOrThrow()
        val original = fixture.dao.rows.getValue(id)
        assertEquals(listOf(1), fixture.scheduledDepths)
        assertTrue(fixture.api.calls.isEmpty())
        val payload = requireNotNull(fixture.adapter.readSupportedOccurrence(original.payload))
        assertEquals(fixture.binding.ownerKey, original.ownerKey)
        assertEquals(fixture.binding.bindingRevision, payload.originBindingRevision)
        assertEquals("2026-09", payload.period)
        assertEquals(7L, payload.request.expectedSeriesRowVersion)
        assertEquals(3L, payload.request.expectedExpenseRowVersion)

        assertEquals(1, fixture.engine(fixture.outbox, fixture.clock).drainOnce().retryable)
        assertEquals(original.payload, fixture.dao.rows.getValue(id).payload)
        val laterClock = Clock.offset(fixture.clock, Duration.ofMinutes(2))
        fixture.api.loseResponse = false
        assertEquals(1, fixture.engine(fixture.newOutbox(laterClock), laterClock).drainOnce().done)
        assertEquals(2, fixture.api.calls.size)
        assertEquals(fixture.api.calls.first(), fixture.api.calls.last())
        assertEquals(original.idempotencyKey, fixture.api.calls.last().second)
        assertEquals(1, fixture.api.results.size)
        assertEquals(PendingMutationStatus.Done.wireValue, fixture.dao.rows.getValue(id).status)
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
    val scheduledDepths = mutableListOf<Int>()
    val outbox = newOutbox(clock)
    val adapter = OutboxAdapterGraph().recurringOccurrenceAdapter
    val repository = RecurringOccurrenceRepository(provider, outbox, adapter)
    val draft = OccurrencePaymentDraft(occurrenceFixture(), "房租",
        RecurringOccurrencePaymentRequestDto("link", 0, 7, "payment-1", 3), "房租付款", 10_000, CurrencyCode.CNY)

    fun newOutbox(clock: Clock) = OutboxRepository(dao, clock,
        bindingProvider = { provider.currentSession().toOutboxBinding() },
        onEnqueued = { scheduledDepths += dao.rows.size })

    fun engine(outbox: OutboxRepository, clock: Clock) = OutboxDrainEngine(outbox,
        listOf(RecurringOccurrenceDispatcher({ api }, adapter)), now = clock::millis)
}

private class OccurrenceApiProbe : ApiService by FakeApiService(mutableListOf(), 0) {
    val calls = mutableListOf<Pair<RecurringOccurrencePaymentRequestDto, String>>()
    val results = mutableMapOf<String, RecurringOccurrenceDto>()
    var loseResponse = true

    override suspend fun setRecurringOccurrencePayment(
        publicId: String, month: String, request: RecurringOccurrencePaymentRequestDto, idempotencyKey: String,
    ): RecurringOccurrenceDto {
        assertEquals("recurring-1", publicId)
        assertEquals("2026-09", month)
        calls += request to idempotencyKey
        val result = results.getOrPut(idempotencyKey) {
            occurrenceFixture().copy(rowVersion = 1, state = "fulfilled", reservedAmountCents = 0,
                expensePublicId = request.expensePublicId, paidAmountCents = 10_000, nextDueDate = "2026-10-05")
        }
        if (loseResponse) throw IOException("Synthetic lost response after commit")
        return result
    }
}

private fun occurrenceFixture() = RecurringOccurrenceDto("recurring-1", "2026-09", 7, 0, "unfulfilled",
    10_000, 10_000, null, null, "2026-09-05")

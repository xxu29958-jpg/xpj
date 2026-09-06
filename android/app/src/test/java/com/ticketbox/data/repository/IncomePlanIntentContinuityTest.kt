package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.IncomePlanDto
import com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto
import com.ticketbox.domain.model.CurrencyCode
import java.io.IOException
import java.time.Clock
import java.time.Duration
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class IncomePlanIntentContinuityTest {
    @Test
    fun durableIntentPrecedesNetworkAndOctoberReplayKeepsSeptemberCommand() = runTest {
        val fixture = IncomeIntentFixture()
        val id = fixture.enqueue().getOrThrow()
        val original = fixture.dao.rows.getValue(id)
        assertEquals(listOf(1), fixture.scheduledDepths)
        assertTrue(fixture.api.calls.isEmpty())
        val intent = assertNotNull(fixture.adapter.readSupportedIncomeEdit(original.payload))
        assertEquals("2026-09", intent.request.intentMonth)
        assertEquals(fixture.binding.bindingRevision, intent.originBindingRevision)
        assertEquals(fixture.binding.ownerKey, original.ownerKey)
        assertEquals(3L, original.expectedRowVersion)
        assertEquals(0L, intent.request.expectedRowVersion)
        assertEquals("工资", intent.originalLabel)
        assertEquals(120_000L, intent.request.amountCents)

        assertEquals(1, fixture.engine(fixture.outbox, fixture.clock).drainOnce().retryable)
        assertEquals(original.payload, fixture.dao.rows.getValue(id).payload)
        val october = Clock.offset(fixture.clock, Duration.ofDays(31))
        fixture.api.loseResponse = false
        assertEquals(1, fixture.engine(fixture.newOutbox(october), october).drainOnce().done)
        assertEquals(2, fixture.api.calls.size)
        assertEquals(fixture.api.calls.first(), fixture.api.calls.last())
        assertEquals(original.idempotencyKey, fixture.api.calls.last().second)
        assertEquals(1, fixture.api.results.size)
    }

    @Test
    fun oldMonthlessAndUnknownPayloadsStayVisibleWithoutDispatch() = runTest {
        for (legacy in listOf(true, false)) {
            val fixture = IncomeIntentFixture()
            val id = fixture.enqueue().getOrThrow()
            val original = fixture.dao.rows.getValue(id)
            val payload = if (legacy) """{"expected_row_version":0,"amount_cents":120000}"""
                else original.payload.replace("\"revision\":1", "\"revision\":99")
            fixture.dao.rows[id] = original.copy(payload = payload)
            assertEquals(1, fixture.engine(fixture.outbox, fixture.clock).drainOnce().failures)
            assertTrue(fixture.api.calls.isEmpty())
            assertEquals(PendingMutationStatus.Failed.wireValue, fixture.dao.rows.getValue(id).status)
            assertEquals(payload, fixture.dao.rows.getValue(id).payload)
            assertEquals(original.idempotencyKey, fixture.dao.rows.getValue(id).idempotencyKey)
        }
    }

    @Test
    fun pendingEditAndChangedBindingCannotPublishAnotherCommand() = runTest {
        val pending = IncomeIntentFixture()
        pending.enqueue().getOrThrow()
        assertTrue(pending.enqueue().isFailure)
        assertEquals(1, pending.dao.rows.size)
        val changed = IncomeIntentFixture()
        changed.session.switchLedgerForFixture("other", "另一本账")
        assertTrue(changed.enqueue().isFailure)
        assertTrue(changed.dao.rows.isEmpty())
    }
}

private class IncomeIntentFixture {
    val session = TestSessionFixture().apply { saveToken("synthetic-session") }
    val api = IncomeIntentApi()
    val provider = testApiServiceProvider(object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
    }, session)
    val binding = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding())
    val dao = FakePendingMutationDao()
    val clock: Clock = Clock.fixed(Instant.parse("2026-09-06T00:00:00Z"), ZoneOffset.UTC)
    val scheduledDepths = mutableListOf<Int>()
    val adapter = OutboxAdapterGraph().incomePlanUpdateAdapter
    val outbox = newOutbox(clock)
    val repository = IncomePlanRepository(provider, outbox, adapter)

    suspend fun enqueue() = repository.enqueueUpdate(binding, incomeIntentDto().toDomain(),
        IncomePlanPatch(expectedRowVersion = 3, intentMonth = "2026-09", amountCents = 120_000), CurrencyCode.CNY)

    fun newOutbox(clock: Clock) = OutboxRepository(dao, clock,
        bindingProvider = { provider.currentSession().toOutboxBinding() },
        onEnqueued = { scheduledDepths += dao.rows.size })

    fun engine(outbox: OutboxRepository, clock: Clock) = OutboxDrainEngine(outbox,
        listOf(UpdateIncomePlanDispatcher({ api }, adapter)), now = clock::millis)
}

private class IncomeIntentApi : ApiService by FakeApiService(mutableListOf(), 0) {
    val calls = mutableListOf<Pair<IncomePlanUpdateRequestDto, String>>()
    val results = mutableMapOf<String, IncomePlanDto>()
    var loseResponse = true

    override suspend fun updateIncomePlan(publicId: String, request: IncomePlanUpdateRequestDto,
        idempotencyKey: String?): IncomePlanDto {
        assertEquals("income-1", publicId)
        assertEquals("2026-09", request.intentMonth)
        calls += request to requireNotNull(idempotencyKey)
        val result = results.getOrPut(idempotencyKey) { incomeIntentDto().copy(amountCents = 120_000, rowVersion = 4) }
        if (loseResponse) throw IOException("Synthetic lost response after commit")
        return result
    }
}

private fun incomeIntentDto() = IncomePlanDto("income-1", "工资", "salary", "monthly", null,
    100_000, 10, "active", "2026-08-01T00:00:00Z", "2026-08-01T00:00:00Z", 3, null)

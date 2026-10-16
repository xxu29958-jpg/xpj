package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.IncomePlanDto
import com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto
import com.ticketbox.data.remote.dto.IncomePlanTokenRequestDto
import com.ticketbox.domain.model.CurrencyCode
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class IncomePlanIntentContinuityTest {
    @Test
    fun oldMonthlessAndUnknownPayloadsStayVisibleWithoutDispatch() = runTest {
        for (legacy in listOf(true, false)) {
            val fixture = IncomeIntentFixture()
            val id = fixture.enqueue().getOrThrow()
            val original = fixture.dao.rows.getValue(id)
            val payload = if (legacy) """{"expected_row_version":0,"amount_cents":120000}"""
                else original.payload.replace("\"revision\":1", "\"revision\":99")
            fixture.dao.rows[id] = original.copy(payload = payload)
            fixture.dao.runnableBatches += listOf(id)
            assertEquals(1, fixture.engine().drainOnce().failures)
            assertTrue(fixture.api.calls.isEmpty())
            assertEquals(PendingMutationStatus.Failed.wireValue, fixture.dao.rows.getValue(id).status)
            assertEquals(payload, fixture.dao.rows.getValue(id).payload)
            assertEquals(original.idempotencyKey, fixture.dao.rows.getValue(id).idempotencyKey)
            val failed = fixture.outbox.observeStatus().first().failed.single()
            val pending = assertNotNull(fixture.repository.describeSubmission(failed))
            assertTrue(!pending.hasSupportedIntent)
            assertTrue(fixture.repository.recoverSubmission(fixture.binding, pending, drop = false).isFailure)
            assertEquals(PendingMutationStatus.Failed.wireValue, fixture.dao.rows.getValue(id).status)
            assertEquals(payload, fixture.dao.rows.getValue(id).payload)
        }
    }

    @Test
    fun pendingEditAndChangedBindingCannotPublishAnotherCommand() = runTest {
        val pending = IncomeIntentFixture()
        pending.enqueue().getOrThrow()
        assertTrue(pending.enqueue().isFailure)
        assertTrue(pending.repository.archive(pending.binding, "income-1", 3, "2026-09").isFailure)
        assertTrue(pending.repository.restore(pending.binding, "income-1", 3, "2026-09").isFailure)
        assertEquals(0, pending.api.lifecycleCalls)
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
    val clock: Clock = Clock.fixed(Instant.parse("2026-09-30T15:30:00Z"), ZoneOffset.UTC)
    val adapter = OutboxAdapterGraph().incomePlanSubmissionAdapter
    val outbox = OutboxRepository(onRowsDeleted = {}, dao = dao, clock = clock,
        bindingProvider = { provider.currentSession().toOutboxBinding() })
    val repository = testIncomePlanRepository(provider, outbox, adapter, OutboxAdapterGraph().incomePlanReceiptAdapter)

    suspend fun enqueue() = repository.enqueueUpdate(binding, incomeIntentDto().toDomain(),
        IncomePlanPatch(expectedRowVersion = 3, intentMonth = "2026-09", amountCents = 120_000), CurrencyCode.CNY)

    fun engine() = OutboxDrainEngine(outbox,
        listOf(IncomePlanDispatcher(com.ticketbox.data.local.PendingMutationType.UpdateIncomePlan, { api }, adapter, OutboxAdapterGraph().incomePlanReceiptAdapter)), now = clock::millis)
}

private class IncomeIntentApi : ApiService by FakeApiService(mutableListOf(), 0) {
    var lifecycleCalls = 0
    val calls = mutableListOf<Pair<IncomePlanUpdateRequestDto, String>>()

    override suspend fun archiveIncomePlan(publicId: String, request: IncomePlanTokenRequestDto): IncomePlanDto {
        lifecycleCalls += 1
        return incomeIntentDto()
    }

    override suspend fun restoreIncomePlan(publicId: String, request: IncomePlanTokenRequestDto): IncomePlanDto {
        lifecycleCalls += 1
        return incomeIntentDto()
    }

    override suspend fun updateIncomePlan(publicId: String, request: IncomePlanUpdateRequestDto,
        idempotencyKey: String?): IncomePlanDto {
        calls += request to requireNotNull(idempotencyKey)
        error("Unsupported original income intent must never reach the network")
    }
}

private fun incomeIntentDto() = IncomePlanDto("income-1", "工资", "salary", "monthly", null,
    100_000, 10, "active", "2026-08-01T00:00:00Z", "2026-08-01T00:00:00Z", 3, null, homeCurrencyCode = "CNY")

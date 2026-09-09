package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.domain.model.GoalDraft
import java.io.IOException
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class GoalCreationRepositoryTest {
    @Test fun creationIsDurableBeforeAnyRemoteWriteAndKeepsCapturedCurrency() = runTest {
        val fixture = GoalCreationFixture()
        fixture.create().getOrThrow()
        assertEquals(0, fixture.keys.size)
        assertEquals(listOf(1), fixture.scheduledDepth)
        val pending = fixture.pending()
        assertEquals("JPY", pending.request?.homeCurrencyCode)
        assertEquals(1200L, pending.request?.targetAmountCents)
        assertEquals("goal_create:${pending.row.idempotencyKey}", pending.row.targetId)
        assertEquals(0L, pending.row.expectedRowVersion)
    }

    @Test fun lostAcknowledgementRetriesOriginalKeyAndAcceptsOnlyOriginalReceipt() = runTest {
        val fixture = GoalCreationFixture()
        fixture.create().getOrThrow()
        val original = fixture.pending().row
        fixture.loseAck = true
        assertEquals(1, fixture.engine().drainOnce().failures)
        val failed = fixture.pending()
        assertTrue(failed.canRetry)
        fixture.loseAck = false
        fixture.repository.recoverCreation(fixture.binding, failed, drop = false).getOrThrow()
        assertEquals(1, fixture.engine().drainOnce().done)
        val done = fixture.pending()
        assertEquals(listOf(original.idempotencyKey, original.idempotencyKey), fixture.keys)
        assertEquals(1, fixture.accepted.size)
        assertEquals(listOf(original.id), fixture.acceptedRows)
        assertEquals(original.payloadJson, done.row.payloadJson)
        assertEquals(1L, done.confirmed?.rowVersion)
        assertEquals("JPY", done.confirmed?.homeCurrencyCode)
    }

    @Test fun differentReceiptCannotSettleAnUnconfirmedCreation() = runTest {
        val fixture = GoalCreationFixture()
        fixture.create().getOrThrow()
        fixture.wrongReceipt = true
        assertEquals(1, fixture.engine().drainOnce().failures)
        val failed = fixture.pending()
        assertEquals(PendingMutationStatus.Failed, failed.row.status)
        assertFalse(failed.canRetry)
        assertEquals(null, failed.confirmed)
        assertTrue(fixture.acceptedRows.isEmpty())
    }

    @Test fun missingCurrencyKeepsOriginalBytesWithoutSendingOrOfferingRetry() = runTest {
        val fixture = GoalCreationFixture()
        fixture.create().getOrThrow()
        val original = fixture.pending().row
        val unknown = original.copy(payloadJson = original.payloadJson.replace("\"home_currency_code\":\"JPY\"", "\"home_currency_code\":null"))
        val dispatcher = CreateGoalDispatcher({ fixture.api }, fixture.adapters.goalCreateAdapter,
            fixture.adapters.goalReceiptAdapter) { error("An unknown original cannot invalidate a query") }
        assertTrue(dispatcher.dispatch(unknown) is DispatchResult.Failure)
        assertTrue(fixture.keys.isEmpty())
        val described = fixture.repository.describeCreation(unknown.copy(status = PendingMutationStatus.Failed,
            lastError = "client_upgrade_required"))!!
        assertFalse(described.canRetry)
        assertEquals(1200L, described.request?.targetAmountCents)
        assertEquals(unknown.payloadJson, described.row.payloadJson)
    }

    @Test fun foreignBindingCannotCreateOrDescribeAnotherOriginsIntent() = runTest {
        val fixture = GoalCreationFixture()
        assertTrue(fixture.repository.create(fixture.binding.copy(ledgerId = "other"), fixture.draft).isFailure)
        assertTrue(fixture.dao.rows.isEmpty())
        fixture.create().getOrThrow()
        val row = fixture.pending().row
        assertEquals(null, fixture.repository.describeCreation(row.copy(serverUrl = "https://other.example")))
        assertEquals(null, fixture.repository.describeCreation(row.copy(ledgerId = "other")))
    }

    @Test fun protocolAndMissingRouteRefusalsNeverSettleCreationAsDone() = runTest {
        for ((status, code) in listOf(409 to "client_upgrade_required", 404 to "not_found")) {
            val fixture = GoalCreationFixture()
            fixture.create().getOrThrow()
            val original = fixture.pending().row
            fixture.httpError = HttpException(Response.error<GoalDto>(status,
                """{"error":"$code","message":"Synthetic refusal"}""".toResponseBody("application/json".toMediaType())))
            assertEquals(1, fixture.engine().drainOnce().failures)
            val failed = fixture.pending()
            assertEquals(PendingMutationStatus.Failed, failed.row.status)
            assertEquals(original.payloadJson, failed.row.payloadJson)
            assertEquals(original.idempotencyKey, failed.row.idempotencyKey)
            assertEquals(code == "client_upgrade_required", failed.canRetry)
            assertTrue(fixture.accepted.isEmpty())
        }
    }

    @Test fun liveReadonlyAccessRejectsCreationBeforeQueueOrNetwork() = runTest {
        val fixture = GoalCreationFixture()
        fixture.session.switchLedgerForFixture("owner", "原账本", "viewer")
        assertTrue(fixture.create().isFailure)
        assertTrue(fixture.dao.rows.isEmpty())
        assertTrue(fixture.keys.isEmpty())
    }
}

private class GoalCreationFixture {
    val session = TestSessionFixture().apply { saveToken("synthetic-session") }
    val dao = FakePendingMutationDao()
    val adapters = OutboxAdapterGraph()
    val scheduledDepth = mutableListOf<Int>()
    private val outbox = testOutboxRepository(dao, onEnqueued = { scheduledDepth += dao.rows.size })
    val keys = mutableListOf<String?>()
    val accepted = mutableMapOf<String, GoalDto>()
    val acceptedRows = mutableListOf<Long>()
    var loseAck = false
    var wrongReceipt = false
    var httpError: HttpException? = null
    val draft = GoalDraft(" Travel ", "2026-09", 1200, "交通", "jpy")
    val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
        override suspend fun createGoal(request: GoalCreateRequestDto, timezone: String?, idempotencyKey: String?): GoalDto {
            keys += idempotencyKey
            httpError?.let { throw it }
            val receipt = accepted.getOrPut(requireNotNull(idempotencyKey)) {
                GoalDto("created-goal", "owner", request.name, "spending_limit", "monthly", request.month, request.category,
                    request.targetAmountCents, 0, request.targetAmountCents, 0, "not_started", "active",
                    "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z", 1, null, homeCurrencyCode = "JPY")
            }
            if (loseAck) throw IOException("Synthetic lost acknowledgement")
            return if (wrongReceipt) receipt.copy(homeCurrencyCode = "CNY") else receipt
        }
    }
    private val provider = testApiServiceProvider(object : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?) = api
    }, session)
    val repository = GoalEditRepository(provider, outbox, adapters.goalUpdateAdapter, adapters.goalReceiptAdapter, adapters.goalCreateAdapter)
    val binding = repository.currentAccess()!!.binding
    suspend fun create() = repository.create(binding, draft)
    suspend fun pending() = repository.observeCreations(binding).first().single()
    fun engine() = OutboxDrainEngine(outbox, listOf(CreateGoalDispatcher({ api },
        adapters.goalCreateAdapter, adapters.goalReceiptAdapter) { acceptedRows += it.id }), maxAttempts = 1)
}

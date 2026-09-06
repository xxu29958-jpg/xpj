package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.CURRENT_TICKETBOX_API_VERSION
import com.ticketbox.data.remote.buildApiHttpClient
import com.ticketbox.data.remote.buildApiService
import com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto
import com.ticketbox.data.remote.dto.RuntimeWriteCompatibility
import java.time.Clock
import java.time.Instant
import java.time.ZoneOffset
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import org.junit.Test
import org.junit.runner.RunWith
import org.junit.runners.Parameterized
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/** Real negotiation, Retrofit, dispatcher and drain; only transport and the DAO are fakes. */
@RunWith(Parameterized::class)
class OutboxProtocolRefusalTest(private val refusal: String) {
    @Test
    fun refusedCommandRemainsRecoverableAndRetriesItsOriginalIntent() = runTest {
        val clock = Clock.fixed(Instant.parse("2026-09-30T23:55:00Z"), ZoneOffset.UTC)
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao, clock)
        val adapter = Moshi.Builder().add(KotlinJsonAdapterFactory()).build().adapter(IncomePlanEditPayload::class.java)
        val payload = IncomePlanEditPayload(1, "plan-1", "工资", 10000, "CNY", "session", "binding",
            IncomePlanUpdateRequestDto("2026-09", 0, amountCents = 12000))
        val id = outbox.enqueue(PendingMutationType.UpdateIncomePlan, "income_plan:plan-1", adapter.toJson(payload), 7, "original-key")
        val original = dao.rows.getValue(id)
        val transport = RefusalTransport(refusal)
        val client = buildApiHttpClient(null, { "synthetic-session" }, { "owner" }, null, null)
            .newBuilder().addInterceptor(transport::respond).build()
        val api = buildApiService("https://example.test/", client)
        val engine = OutboxDrainEngine(outbox, listOf(UpdateIncomePlanDispatcher({ api }, adapter)), now = clock::millis)
        var committedNotifications = 0
        engine.onAdviceInputReplaySucceeded = { committedNotifications++ }

        // The worker's first read is compatible; negotiation can change before the individual write.
        OutboxDrainWorker.runCompatibleDrain(
            compatibility = { RuntimeWriteCompatibility.compatible(CURRENT_TICKETBOX_API_VERSION, "1:1:CNY") },
            drain = engine::drainOnce,
        )

        val retained = dao.rows.getValue(id)
        assertEquals(PendingMutationStatus.Failed.wireValue, retained.status)
        assertNull(retained.completedAt)
        assertTrue(retained.lastError.orEmpty().isNotBlank())
        if (refusal != "future_write_refusal") assertEquals(refusal, retained.lastError)
        assertEquals(original, retained.copy(status = original.status, retryCount = original.retryCount,
            attemptedAt = original.attemptedAt, lastError = original.lastError))
        assertEquals(if (refusal == "runtime_version_mismatch") 0 else 1, transport.mutations.size)
        assertEquals(0, committedNotifications)
        assertEquals(id, outbox.activeForTarget("income_plan:plan-1").single().id)

        transport.accept = true
        assertTrue(outbox.resolveFailed(id, FailedResolution.Retry()))
        assertEquals(1, engine.drainOnce().done)
        assertEquals(PendingMutationStatus.Done.wireValue, dao.rows.getValue(id).status)
        assertEquals(1, committedNotifications)
        transport.mutations.forEach { (key, body) ->
            assertEquals("original-key", key)
            assertEquals(payload.request.copy(expectedRowVersion = original.expectedRowVersion), adapterRequest.fromJson(body))
        }
    }

    private val adapterRequest = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
        .adapter(IncomePlanUpdateRequestDto::class.java)

    companion object {
        @JvmStatic
        @Parameterized.Parameters(name = "{0}")
        fun refusals() = listOf("runtime_version_mismatch", "client_upgrade_required", "future_write_refusal")
    }
}

private class RefusalTransport(private val refusal: String) {
    var accept = false
    val mutations = mutableListOf<Pair<String?, String>>()

    fun respond(chain: okhttp3.Interceptor.Chain): Response {
        val request = chain.request()
        val read = request.method == "GET"
        if (!read) mutations += request.header("Idempotency-Key") to Buffer().also { request.body!!.writeTo(it) }.readUtf8()
        val version = if (!accept && refusal == "runtime_version_mismatch") "2026-08-02" else CURRENT_TICKETBOX_API_VERSION
        val body = when {
            read -> """{"api_version":"$version","write_compatibility":"compatible","capabilities":{"currency":{"request_binding":"1:1:CNY"}}}"""
            accept -> """{"public_id":"plan-1","label":"工资","source_type":"salary","frequency":"monthly","amount_cents":12000,"pay_day":15,"status":"active","created_at":"2026-09-01T00:00:00Z","updated_at":"2026-09-30T23:55:00Z","row_version":8}"""
            else -> """{"error":"$refusal","message":"请更新配套版本后重试，原提交应保留。"}"""
        }
        return Response.Builder().request(request).protocol(Protocol.HTTP_1_1)
            .code(if (read || accept) 200 else 409).message("Synthetic response")
            .body(body.toResponseBody("application/json".toMediaType())).build()
    }
}

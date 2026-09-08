package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.CURRENT_TICKETBOX_API_VERSION
import com.ticketbox.data.remote.TICKETBOX_API_VERSION_HEADER
import com.ticketbox.data.remote.TICKETBOX_CURRENCY_BINDING_HEADER
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
        when (refusal) {
            "currency_adoption_required" -> assertEquals(ADOPTION_GUIDANCE, retained.lastError)
            "currency_binding_configuration_drift" -> assertEquals(DRIFT_GUIDANCE, retained.lastError)
            "currency_binding_revision_conflict" -> assertTrue(retained.lastError.orEmpty().isNotBlank())
            "future_write_refusal" -> Unit
            else -> assertEquals(refusal, retained.lastError)
        }
        assertEquals(original, retained.copy(status = original.status, retryCount = original.retryCount,
            attemptedAt = original.attemptedAt, lastError = original.lastError))
        if (refusal == "currency_adoption_required") {
            assertEquals(listOf<String?>(CURRENT_TICKETBOX_API_VERSION), transport.mutationVersions)
            assertTrue(transport.currencyBindings.all { it == null })
        }
        if (refusal == "currency_binding_configuration_drift") {
            assertEquals(listOf<String?>(CURRENT_TICKETBOX_API_VERSION), transport.mutationVersions)
            assertEquals(listOf<String?>(null, "1:7:JPY"), transport.currencyBindings)
        }
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
        fun refusals() = listOf("runtime_version_mismatch", "client_upgrade_required", "future_write_refusal",
            "currency_adoption_required", "currency_binding_configuration_drift", "currency_binding_revision_conflict")
    }
}

private class RefusalTransport(private val refusal: String) {
    var accept = false
    val mutations = mutableListOf<Pair<String?, String>>()
    val mutationVersions = mutableListOf<String?>()
    val currencyBindings = mutableListOf<String?>()

    fun respond(chain: okhttp3.Interceptor.Chain): Response {
        val request = chain.request()
        currencyBindings += request.header(TICKETBOX_CURRENCY_BINDING_HEADER)
        val read = request.method == "GET"
        if (!read) {
            mutations += request.header("Idempotency-Key") to Buffer().also { request.body!!.writeTo(it) }.readUtf8()
            mutationVersions += request.header(TICKETBOX_API_VERSION_HEADER)
        }
        val body = when {
            read -> compatibilityBody()
            accept -> """{"public_id":"plan-1","label":"工资","source_type":"salary","frequency":"monthly","amount_cents":12000,"pay_day":15,"status":"active","created_at":"2026-09-01T00:00:00Z","updated_at":"2026-09-30T23:55:00Z","row_version":8}"""
            else -> refusalBody(request)
        }
        return Response.Builder().request(request).protocol(Protocol.HTTP_1_1)
            .code(if (read || accept) 200 else 409).message("Synthetic response")
            .body(body.toResponseBody("application/json".toMediaType())).build()
    }

    private fun compatibilityBody(): String {
        val version = if (!accept && refusal == "runtime_version_mismatch") "2026-08-02" else CURRENT_TICKETBOX_API_VERSION
        return when {
            !accept && refusal == "currency_adoption_required" ->
                """{"api_version":"$version","write_compatibility":"owner_action_required","capabilities":{"currency":{"request_binding":null}}}"""
            !accept && refusal == "currency_binding_configuration_drift" ->
                """{"api_version":"$version","write_compatibility":"configuration_required","capabilities":{"currency":{"request_binding":"1:7:JPY"}}}"""
            else -> """{"api_version":"$version","write_compatibility":"compatible","capabilities":{"currency":{"request_binding":"1:1:CNY"}}}"""
        }
    }

    private fun refusalBody(request: okhttp3.Request): String {
        val currentProtocol = request.header(TICKETBOX_API_VERSION_HEADER) == CURRENT_TICKETBOX_API_VERSION
        return when (refusal) {
            "currency_adoption_required" -> if (currentProtocol) {
                """{"error":"currency_adoption_required","message":"Owner confirmation required."}"""
            } else MISSING_NEGOTIATION
            "currency_binding_configuration_drift" -> if (currentProtocol &&
                request.header(TICKETBOX_CURRENCY_BINDING_HEADER) == "1:7:JPY"
            ) {
                """{"error":"currency_binding_configuration_drift","message":"$DRIFT_GUIDANCE"}"""
            } else MISSING_NEGOTIATION
            else -> """{"error":"$refusal","message":"请更新配套版本后重试，原提交应保留。"}"""
        }
    }
}

private const val ADOPTION_GUIDANCE =
    "这台小票夹正在等待安装拥有者在电脑端确认本位币。你的草稿和待同步操作会保留，确认后请重试。"
private const val DRIFT_GUIDANCE = "服务端币种配置与已持久化的本位币绑定不一致，已停止写入。"
private const val MISSING_NEGOTIATION =
    """{"error":"client_upgrade_required","message":"Income requires the current protocol and currency binding."}"""

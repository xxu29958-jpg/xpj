package com.ticketbox.data.repository

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.CURRENT_TICKETBOX_API_VERSION
import com.ticketbox.data.remote.TICKETBOX_CURRENCY_BINDING_HEADER
import com.ticketbox.data.remote.buildApiHttpClient
import com.ticketbox.data.remote.buildApiService
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class ManualExpenseCurrencyRoomTest {
    private val fixture = ExpenseCorrectionConnectedFixture(ApplicationProvider.getApplicationContext<Context>())

    @After fun close() { fixture.close() }

    @Test
    fun currentJpyNegotiationCanResumeTheOriginalCnySubmissionAfterRevisionRefusal() = runBlocking {
        fixture.reopen()
        val adapters = OutboxAdapterGraph()
        val request = ExpenseManualCreateRequestDto(originalCurrency = "CNY", originalAmount = "12.34",
            homeCurrencyCode = "CNY", merchant = "shop", category = "other", note = null,
            expenseTime = "2026-09-09T00:00:00Z", tags = null, valueScore = null, regretScore = null,
            clientRef = "cny-original-ref")
        val payload = adapters.manualCreateAdapter.toJson(request)
        val id = fixture.outbox.enqueue(PendingMutationType.CreateExpense, "expense:local:cny-original-ref", payload, 0)
        val original = fixture.stored().single()
        fixture.reopen()
        var accept = false
        val bodies = mutableListOf<String>()
        val bindings = mutableListOf<String?>()
        val accepted = fixture.network.current.copy(homeCurrency = "CNY", originalCurrencyCode = "CNY",
            originalAmountMinor = 1234, amountCents = 1234)
        val receipt = Moshi.Builder().add(KotlinJsonAdapterFactory()).build().adapter(ExpenseDto::class.java).toJson(accepted)
        val client = buildApiHttpClient(null, { "test-session" }, { "owner" }, null, null).newBuilder()
            .addInterceptor { chain ->
                val read = chain.request().method == "GET"
                val body = if (read) {
                    """{"api_version":"$CURRENT_TICKETBOX_API_VERSION","write_compatibility":"compatible","capabilities":{"currency":{"request_binding":"1:2:JPY","home_currency_code":"JPY"}}}"""
                } else {
                    val buffer = Buffer()
                    requireNotNull(chain.request().body).writeTo(buffer)
                    bodies += buffer.readUtf8()
                    bindings += chain.request().header(TICKETBOX_CURRENCY_BINDING_HEADER)
                    if (accept) receipt else """{"error":"currency_binding_revision_conflict","message":"Review original submission"}"""
                }
                Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(if (read || accept) 200 else 409)
                    .message("Response").body(body.toResponseBody("application/json".toMediaType())).build()
            }.build()
        val api = buildApiService("https://example.test/", client)
        val dispatcher = CreateExpenseDispatcher({ api }, adapters.manualCreateAdapter) { ledger, ref, value ->
            fixture.expenseDao.applyLocalCreateServerIdentity(ledger, value.toEntity(ledger).copy(clientRef = ref))
        }
        val engine = OutboxDrainEngine(fixture.outbox, listOf(dispatcher), now = fixture.clock::millis)
        assertEquals(0, engine.drainOnce().done)
        val refused = fixture.stored().single()
        assertEquals(PendingMutationStatus.Failed.wireValue, refused["status"])
        assertNull(refused["completedAt"])
        assertOriginalColumns(original, refused)
        accept = true
        assertTrue(fixture.outbox.resolveFailed(id, FailedResolution.Retry()))
        assertEquals(1, engine.drainOnce().done)
        assertEquals(listOf(payload, payload), bodies)
        assertEquals(listOf<String?>("1:2:JPY", "1:2:JPY"), bindings)
        assertEquals("CNY", fixture.expenseDao.getConfirmed(requireNotNull(original["ledgerId"])).single().homeCurrencyCode)
        assertEquals(payload, fixture.stored().single()["payload"])
    }

    @Test
    fun legacyMissingCurrencySurvivesReopenAndRefusalWithOriginalBytes() = runBlocking {
        fixture.reopen()
        val adapter = OutboxAdapterGraph().manualCreateAdapter
        val payload = adapter.toJson(ExpenseManualCreateRequestDto(originalAmount = "12.34", merchant = "shop",
            category = "other", note = "original draft", expenseTime = "2026-09-09T00:00:00Z",
            tags = null, valueScore = null, regretScore = null, clientRef = "legacy-original-ref"))
        fixture.outbox.enqueue(PendingMutationType.CreateExpense, "expense:local:legacy-original-ref", payload, 0)
        val before = fixture.stored().single()
        fixture.reopen()
        val dispatcher = CreateExpenseDispatcher(apiProvider = { error("Missing currency must not reach HTTP") },
            payloadAdapter = adapter, applyServerIdentity = { _, _, _ -> error("No unverified success") })
        val result = OutboxDrainEngine(fixture.outbox, listOf(dispatcher), now = fixture.clock::millis).drainOnce()
        assertEquals(0, result.done)
        val after = fixture.stored().single()
        assertEquals(PendingMutationStatus.Failed.wireValue, after["status"])
        assertNull(after["completedAt"])
        assertTrue(after["lastError"].orEmpty().contains("manual_create_original_unverified"))
        assertOriginalColumns(before, after)
        assertEquals(payload, after["payload"])
    }

    private fun assertOriginalColumns(before: Map<String, String?>, after: Map<String, String?>) {
        val operational = setOf("status", "retryCount", "attemptedAt", "lastError")
        assertEquals(before.filterKeys { it !in operational }, after.filterKeys { it !in operational })
    }
}

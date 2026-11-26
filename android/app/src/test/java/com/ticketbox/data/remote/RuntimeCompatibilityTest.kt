package com.ticketbox.data.remote

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.remote.dto.RuntimeCompatibilityDto
import com.ticketbox.data.remote.dto.toWriteCompatibility
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody

class RuntimeCompatibilityTest {
    private val adapter = Moshi.Builder().add(KotlinJsonAdapterFactory()).build().adapter(RuntimeCompatibilityDto::class.java)

    private fun envelope(fields: String = "", version: String = CURRENT_TICKETBOX_API_VERSION) = """{"api_version":"$version",$fields
        "write_compatibility":"compatible","capabilities":{"currency":{"request_binding":"1:1:CNY"},"expense_confirmation_version":2}}"""

    @Test
    fun oldEnvelopeAndExplicitPayloadRevisions() {
        val legacy = requireNotNull(adapter.fromJson(envelope())).toWriteCompatibility()
        assertTrue(legacy.canWrite)
        assertEquals(2, legacy.expenseConfirmationVersion)
        val explicit = requireNotNull(adapter.fromJson(envelope(""""supported_payload_revisions":{"expense_confirmation":[3]},""")))
        assertFalse(explicit.toWriteCompatibility().supportsAtomicConfirmation)
        assertTrue(explicit.copy(supportedPayloadRevisions = mapOf("expense_confirmation" to listOf(2, 3)))
            .toWriteCompatibility().supportsAtomicConfirmation)
        val broken = explicit.copy(minReadClientVersion = "invalid").toWriteCompatibility()
        assertFalse(broken.readerVersionAccepted)
        assertFalse(broken.canWrite)
    }

    @Test
    fun nullFloorsUseTheServerVersionAndDatesMustBeCanonical() {
        val fields = """"min_read_client_version":null,"min_write_client_version":null,"""
        val current = requireNotNull(adapter.fromJson(envelope(fields)))
        assertTrue(current.toWriteCompatibility().canWrite)
        val newer = requireNotNull(adapter.fromJson(envelope(fields, "2026-11-01")))
        assertFalse(newer.readerVersionAccepted)
        assertFalse(newer.copy(minReadClientVersion = CURRENT_TICKETBOX_API_VERSION).writerVersionAccepted)
        val readable = newer.copy(minReadClientVersion = CURRENT_TICKETBOX_API_VERSION,
            capabilities = newer.capabilities.copy(originalAttachmentVersion = 1))
        assertTrue(readable.toWriteCompatibility().supportsOriginalAttachment)
        for (invalid in listOf("-0001-01-01", "+12026-01-01", "2026-02-30", "0000-01-01")) {
            assertFalse(current.copy(apiVersion = invalid, minReadClientVersion = CURRENT_TICKETBOX_API_VERSION).readerVersionAccepted)
            assertFalse(current.copy(minReadClientVersion = invalid).readerVersionAccepted)
        }
    }

    @Test
    fun malformedHandshakesNeverDispatchTheBusinessRequest() {
        for (json in listOf("""{"api_version":null}""", "{", "not json")) {
            val client = buildApiHttpClient(null, { "token" }, { "ledger" }, null, null).newBuilder().addInterceptor { chain ->
                val request = chain.request()
                assertEquals("/api/system/runtime-compatibility", request.url.encodedPath)
                Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(200).message("OK")
                    .body(json.toResponseBody()).build()
            }.build()
            val request = Request.Builder().url("https://example.test/api/expenses").build()
            client.newCall(request).execute().use { assertEquals(409, it.code) }
        }
    }

    @Test
    fun renegotiationKeepsTheCurrencyBindingCapturedByTheOriginalCommand() {
        val captured = "1:7:JPY"
        var dispatched = false
        val client = buildApiHttpClient(null, { "token" }, { "ledger" }, null, null).newBuilder().addInterceptor { chain ->
            val request = chain.request()
            val body = if (request.method == "GET") envelope() else {
                assertEquals(captured, request.header(TICKETBOX_CURRENCY_BINDING_HEADER))
                dispatched = true
                "{}"
            }
            Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(200).message("OK").body(body.toResponseBody()).build()
        }.build()
        val request = Request.Builder().url("https://example.test/api/expenses/manual")
            .header(TICKETBOX_API_VERSION_HEADER, CURRENT_TICKETBOX_API_VERSION)
            .header(TICKETBOX_CURRENCY_BINDING_HEADER, captured).post("{}".toRequestBody()).build()
        client.newCall(request).execute().close()
        assertTrue(dispatched)
    }

    @Test
    fun accountRequestsPresentTheClientProtocolWithoutDependingOnTheSelectedLedger() {
        val paths = mutableListOf<String>()
        val client = buildApiHttpClient(null, { "token" }, { "unavailable-ledger" }, null, null)
            .newBuilder().addInterceptor { chain ->
                val request = chain.request()
                paths += request.url.encodedPath
                assertEquals(CURRENT_TICKETBOX_API_VERSION, request.header(TICKETBOX_API_VERSION_HEADER))
                assertEquals(null, request.header(TICKETBOX_CURRENCY_BINDING_HEADER))
                Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(409).message("Upgrade required")
                    .body("{}".toResponseBody()).build()
            }.build()
        val request = Request.Builder().url("https://example.test/api/settings/account").post("{}".toRequestBody()).build()
        client.newCall(request).execute().use { assertEquals(409, it.code) }
        assertEquals(listOf("/api/settings/account"), paths)
    }

    @Test
    fun ordinaryReadsAndWritesRespectIndependentFloorsBeforeDispatch() {
        fun status(readFloor: String, writeFloor: String, write: Boolean): Int {
            val sent = mutableListOf<String>()
            val client = buildApiHttpClient(null, { "token" }, { "ledger" }, null, null).newBuilder().addInterceptor { chain ->
                val request = chain.request()
                sent += request.url.encodedPath
                if (request.url.encodedPath != "/api/system/runtime-compatibility") {
                    assertEquals("2026-10-11", request.header(TICKETBOX_API_VERSION_HEADER))
                }
                val body = envelope(""""min_read_client_version":"$readFloor","min_write_client_version":"$writeFloor",""", "2026-11-01")
                Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(200).message("OK")
                    .body(body.toResponseBody()).build()
            }.build()
            val request = Request.Builder().url("https://example.test/api/expenses")
                .apply { if (write) post("{}".toRequestBody()) }.build()
            val code = client.newCall(request).execute().use { it.code }
            assertEquals(if (code == 409) listOf("/api/system/runtime-compatibility")
                else listOf("/api/system/runtime-compatibility", "/api/expenses"), sent)
            return code
        }
        val current = CURRENT_TICKETBOX_API_VERSION
        assertEquals(200, status(current, "2026-11-01", false))
        assertEquals(409, status(current, "2026-11-01", true))
        assertEquals(200, status(current, current, true))
        assertEquals(409, status("2099-01-01", current, false))
        assertEquals(409, status("2099-01-01", current, true))
    }
}

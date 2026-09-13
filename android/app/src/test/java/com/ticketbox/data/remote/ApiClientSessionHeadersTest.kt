package com.ticketbox.data.remote

import okhttp3.OkHttpClient
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okhttp3.Protocol
import java.io.IOException
import java.net.ServerSocket
import java.util.concurrent.atomic.AtomicReference
import kotlin.concurrent.thread
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertFalse
import kotlin.test.assertTrue
import kotlin.test.assertFailsWith

class ApiClientSessionHeadersTest {
    @Test
    fun authenticatedRequestsFollowCurrentLedgerAndDoNotLeakWhenUnbound() {
        var token: String? = "tbx_session"
        var ledgerId: String? = "owner"
        val client = buildApiHttpClient(
            routeProvider = null,
            tokenProvider = { token },
            ledgerIdProvider = { ledgerId },
            refreshController = null,
            credentials = null,
        )

        val ownerHeaders = captureRequestHeaders(client)
        assertEquals("Bearer tbx_session", ownerHeaders["authorization"])
        assertEquals("owner", ownerHeaders[LEDGER_ID_HEADER.lowercase()])

        ledgerId = "family-ledger"
        val familyHeaders = captureRequestHeaders(client)
        assertEquals("family-ledger", familyHeaders[LEDGER_ID_HEADER.lowercase()])

        token = null
        ledgerId = "must-not-leak"
        val unboundHeaders = captureRequestHeaders(client)
        assertNull(unboundHeaders["authorization"])
        assertNull(unboundHeaders[LEDGER_ID_HEADER.lowercase()])
    }

    @Test
    fun moneyMutationNegotiatesCurrentJpyBindingBeforeDispatch() {
        val client = buildApiHttpClient(
            routeProvider = null,
            tokenProvider = { "tbx_session" },
            ledgerIdProvider = { "owner" },
            refreshController = null,
            credentials = null,
        )

        val requests = captureNegotiatedMutation(client)

        assertEquals("GET /api/system/runtime-compatibility HTTP/1.1", requests[0].first)
        assertEquals("POST /api/expenses/manual HTTP/1.1", requests[1].first)
        assertEquals(CURRENT_TICKETBOX_API_VERSION, requests[1].second[TICKETBOX_API_VERSION_HEADER.lowercase()])
        assertEquals("1:1:JPY", requests[1].second[TICKETBOX_CURRENCY_BINDING_HEADER.lowercase()])
    }

    @Test
    fun defaultRevisionChangesOnlyNegotiationEvidenceNotTheOriginalManualIntent() {
        var currencyBinding = "1:1:CNY"
        val sent = mutableListOf<Pair<Request, String>>()
        val client = buildApiHttpClient(null, { "tbx_session" }, { "owner" }, null, null)
            .newBuilder().addInterceptor { chain ->
                val request = chain.request()
                val body = if (request.method == "GET") {
                    """{"api_version":"$CURRENT_TICKETBOX_API_VERSION","write_compatibility":"compatible","capabilities":{"currency":{"request_binding":"$currencyBinding"}}}"""
                } else {
                    val buffer = okio.Buffer()
                    requireNotNull(request.body).writeTo(buffer)
                    sent += request to buffer.readUtf8()
                    "{}"
                }
                Response.Builder().request(request).protocol(Protocol.HTTP_1_1)
                    .code(200).message("Response").body(body.toResponseBody("application/json".toMediaType())).build()
            }.build()
        val adapter = com.squareup.moshi.Moshi.Builder()
            .add(com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory()).build()
            .adapter(com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto::class.java)
        val original = adapter.toJson(requireNotNull(adapter.fromJson(
            """{"original_currency":"CNY","original_amount":"12.34","home_currency_code":"CNY","merchant":"shop","category":"other","note":null,"expense_time":"2026-09-09T00:00:00Z","tags":null,"value_score":null,"regret_score":null,"client_ref":"original-manual-intent"}""",
        )))
        val request = Request.Builder().url("https://example.test/api/expenses/manual")
            .post(original.toRequestBody("application/json".toMediaType())).build()
        client.newCall(request).execute().close()
        currencyBinding = "1:2:JPY"
        client.newCall(request).execute().close()
        assertEquals(listOf(original, original), sent.map { it.second })
        assertEquals(listOf<String?>("1:1:CNY", "1:2:JPY"), sent.map { it.first.header(TICKETBOX_CURRENCY_BINDING_HEADER) })
        assertTrue(sent.all { it.first.header("Authorization") == "Bearer tbx_session" })
        assertTrue(sent.all { it.first.header(LEDGER_ID_HEADER) == "owner" })
    }

    @Test
    fun unauthenticatedPairingMutationDoesNotRequireRuntimeNegotiation() {
        val client = buildApiHttpClient(
            routeProvider = null,
            tokenProvider = { null },
            ledgerIdProvider = { null },
            refreshController = null,
            credentials = null,
        )

        val headers = captureRequestHeaders(client, mutation = true)

        assertNull(headers["authorization"])
        assertNull(headers[TICKETBOX_API_VERSION_HEADER.lowercase()])
    }

    @Test
    fun unavailableNegotiationDoesNotSendAnUnnegotiatedMutation() {
        var mutationSent = false
        val client = buildApiHttpClient(null, { "tbx_session" }, { "owner" }, null, null)
            .newBuilder().addInterceptor { chain ->
                if (chain.request().method != "GET") mutationSent = true
                Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
                    .code(500).message("Unavailable").body("".toResponseBody()).build()
            }.build()
        val request = Request.Builder().url("https://example.test/api/expenses/manual")
            .post("{}".toRequestBody()).build()

        assertFailsWith<IOException> { client.newCall(request).execute().close() }
        assertFalse(mutationSent)
    }

    @Test
    fun mismatchedProtocolNeverFallsBackToAnUnversionedIncomeMutation() {
        var mutationSent = false
        val client = buildApiHttpClient(null, { "tbx_session" }, { "owner" }, null, null)
            .newBuilder().addInterceptor { chain ->
                if (chain.request().method != "GET") mutationSent = true
                val body = """{"api_version":"2026-08-02","write_compatibility":"compatible","capabilities":{"currency":{"request_binding":"1:1:CNY"}}}"""
                Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
                    .code(200).message("Response").body(body.toResponseBody("application/json".toMediaType())).build()
            }.build()
        val request = Request.Builder().url("https://example.test/api/income-plans")
            .post("{}".toRequestBody()).build()

        client.newCall(request).execute().use { response ->
            assertEquals(409, response.code)
            kotlin.test.assertTrue(response.body.string().contains("runtime_version_mismatch"))
        }
        assertFalse(mutationSent)
    }

    @Test
    fun changedCurrencyBindingReturnsTheRefusalWithoutAnAutomaticRetry() {
        var mutations = 0
        val client = buildApiHttpClient(null, { "tbx_session" }, { "owner" }, null, null)
            .newBuilder().addInterceptor { chain ->
                val isRead = chain.request().method == "GET"
                val body = if (isRead) {
                    """{"api_version":"$CURRENT_TICKETBOX_API_VERSION","write_compatibility":"compatible","capabilities":{"currency":{"request_binding":"1:1:CNY"}}}"""
                } else {
                    mutations++
                    """{"error":"currency_binding_revision_conflict","message":"Currency binding changed"}"""
                }
                Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
                    .code(if (isRead) 200 else 409).message("Response")
                    .body(body.toResponseBody("application/json".toMediaType())).build()
            }.build()
        val request = Request.Builder().url("https://example.test/api/expenses/manual")
            .post("{}".toRequestBody()).build()

        client.newCall(request).execute().use { response ->
            assertEquals(409, response.code)
            assertTrue(response.body.string().contains("currency_binding_revision_conflict"))
        }
        assertEquals(1, mutations)
    }
}

private fun captureNegotiatedMutation(client: OkHttpClient): List<Pair<String, Map<String, String>>> {
    ServerSocket(0).use { server ->
        server.soTimeout = 5_000
        val captured = AtomicReference<List<Pair<String, Map<String, String>>>>()
        val failure = AtomicReference<Throwable>()
        val worker = thread(name = "ticketbox-runtime-negotiation-probe") {
            try {
                val requests = buildList {
                    repeat(2) { index ->
                        server.accept().use { socket ->
                            val reader = socket.getInputStream().bufferedReader(Charsets.US_ASCII)
                            val requestLine = checkNotNull(reader.readLine())
                            val headers = readHeaders(reader)
                            repeat(headers["content-length"]?.toIntOrNull() ?: 0) { reader.read() }
                            add(requestLine to headers)
                            val responseBody = if (index == 0) {
                                """{"api_version":"$CURRENT_TICKETBOX_API_VERSION","write_compatibility":"compatible","capabilities":{"currency":{"request_binding":"1:1:JPY"}}}"""
                            } else {
                                ""
                            }
                            socket.getOutputStream().bufferedWriter(Charsets.US_ASCII).use { writer ->
                                writer.write(
                                    "HTTP/1.1 ${if (index == 0) "200 OK" else "204 No Content"}\r\n" +
                                        "Content-Type: application/json\r\n" +
                                        "Content-Length: ${responseBody.toByteArray().size}\r\n" +
                                        "Connection: close\r\n\r\n" +
                                        responseBody,
                                )
                            }
                        }
                    }
                }
                captured.set(requests)
            } catch (error: Throwable) {
                failure.set(error)
            }
        }

        client.newCall(
            Request.Builder()
                .url("http://127.0.0.1:${server.localPort}/api/expenses/manual")
                .post("{}".toRequestBody("application/json".toMediaType()))
                .build(),
        ).execute().use { response -> assertEquals(204, response.code) }
        worker.join(5_000)
        failure.get()?.let { throw it }
        check(!worker.isAlive) { "Runtime negotiation probe did not finish" }
        return checkNotNull(captured.get())
    }
}

private fun readHeaders(reader: java.io.BufferedReader): Map<String, String> = buildMap {
    while (true) {
        val line = reader.readLine() ?: break
        if (line.isEmpty()) break
        val separator = line.indexOf(':')
        if (separator > 0) {
            put(line.substring(0, separator).trim().lowercase(), line.substring(separator + 1).trim())
        }
    }
}

private fun captureRequestHeaders(client: OkHttpClient, mutation: Boolean = false): Map<String, String> {
    ServerSocket(0).use { server ->
        server.soTimeout = 5_000
        val captured = AtomicReference<Map<String, String>>()
        val failure = AtomicReference<Throwable>()
        val worker = thread(name = "ticketbox-http-header-probe") {
            try {
                server.accept().use { socket ->
                    val reader = socket.getInputStream().bufferedReader(Charsets.US_ASCII)
                    reader.readLine()
                    val headers = readHeaders(reader)
                    captured.set(headers)
                    socket.getOutputStream().bufferedWriter(Charsets.US_ASCII).use { writer ->
                        writer.write(
                            "HTTP/1.1 204 No Content\r\n" +
                                "Content-Length: 0\r\n" +
                                "Connection: close\r\n\r\n",
                        )
                    }
                }
            } catch (error: Throwable) {
                failure.set(error)
            }
        }

        val request = Request.Builder()
            .url("http://127.0.0.1:${server.localPort}/probe")
            .let { builder ->
                if (mutation) builder.post("{}".toRequestBody("application/json".toMediaType())) else builder
            }
            .build()
        client.newCall(request).execute().use { response ->
            assertEquals(204, response.code)
        }
        worker.join(5_000)
        failure.get()?.let { throw it }
        check(!worker.isAlive) { "HTTP header probe did not finish" }
        return checkNotNull(captured.get())
    }
}

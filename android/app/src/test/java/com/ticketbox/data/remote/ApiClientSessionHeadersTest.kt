package com.ticketbox.data.remote

import okhttp3.OkHttpClient
import okhttp3.Request
import java.net.ServerSocket
import java.util.concurrent.atomic.AtomicReference
import kotlin.concurrent.thread
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

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
}

private fun captureRequestHeaders(client: OkHttpClient): Map<String, String> {
    ServerSocket(0).use { server ->
        server.soTimeout = 5_000
        val captured = AtomicReference<Map<String, String>>()
        val failure = AtomicReference<Throwable>()
        val worker = thread(name = "ticketbox-http-header-probe") {
            try {
                server.accept().use { socket ->
                    val reader = socket.getInputStream().bufferedReader(Charsets.US_ASCII)
                    reader.readLine()
                    val headers = buildMap {
                        while (true) {
                            val line = reader.readLine() ?: break
                            if (line.isEmpty()) break
                            val separator = line.indexOf(':')
                            if (separator > 0) {
                                put(
                                    line.substring(0, separator).trim().lowercase(),
                                    line.substring(separator + 1).trim(),
                                )
                            }
                        }
                    }
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

        client.newCall(
            Request.Builder()
                .url("http://127.0.0.1:${server.localPort}/probe")
                .build(),
        ).execute().use { response ->
            assertEquals(204, response.code)
        }
        worker.join(5_000)
        failure.get()?.let { throw it }
        check(!worker.isAlive) { "HTTP header probe did not finish" }
        return checkNotNull(captured.get())
    }
}

package com.ticketbox.data.remote

import com.ticketbox.data.remote.dto.LedgerRenameRequestDto
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class LedgerNameApiTest {
    @Test
    fun targetLedgerRenameDoesNotRequireCurrencyAccessToTheSelectedLedger() = runTest {
        val sent = mutableListOf<Pair<Request, String>>()
        val client = buildApiHttpClient(null, { "own-session" }, { "removed-ledger" }, null, null)
            .newBuilder().addInterceptor { chain ->
                val request = chain.request()
                val buffer = Buffer()
                request.body?.writeTo(buffer)
                sent += request to buffer.readUtf8()
                val label = request.url.encodedPath == "/api/ledgers/target/name"
                Response.Builder().request(request).protocol(Protocol.HTTP_1_1)
                    .code(if (label) 200 else 403).message("Fixture")
                    .body((if (label) """{"ledger_id":"target","name":"新名称","role":"owner","is_default":false}"""
                        else """{"error":"ledger_forbidden","message":"Removed membership"}""")
                        .toResponseBody("application/json".toMediaType())).build()
            }.build()
        val result = buildApiService("https://example.test/", client).renameLedger("target", LedgerRenameRequestDto("新名称", "原名称"))
        assertEquals("新名称", result.name)
        val (request, body) = sent.single()
        assertEquals("POST", request.method)
        assertEquals("/api/ledgers/target/name", request.url.encodedPath)
        assertEquals("Bearer own-session", request.header("Authorization"))
        assertNull(request.header(TICKETBOX_CURRENCY_BINDING_HEADER))
        assertEquals("""{"name":"新名称","expected_name":"原名称"}""", body)
    }
}

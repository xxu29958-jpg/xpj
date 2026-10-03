package com.ticketbox.data.remote

import com.ticketbox.data.remote.dto.AccountProfileRenameDto
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

class AccountProfileApiTest {
    @Test
    fun ownAccountRenameDoesNotDependOnLedgerCurrencyAccess() = runTest {
        val sent = mutableListOf<Pair<Request, String>>()
        val client = buildApiHttpClient(null, { "own-session" }, { "removed-ledger" }, null, null)
            .newBuilder().addInterceptor { chain ->
                val request = chain.request()
                val buffer = Buffer()
                request.body?.writeTo(buffer)
                sent += request to buffer.readUtf8()
                val account = request.url.encodedPath == "/api/settings/account"
                Response.Builder().request(request).protocol(Protocol.HTTP_1_1)
                    .code(if (account) 200 else 403).message("Fixture")
                    .body((if (account) """{"account_public_id":"self","display_name":"新名称"}"""
                        else """{"error":"ledger_forbidden","message":"Removed membership"}""")
                        .toResponseBody("application/json".toMediaType())).build()
            }.build()
        val api = buildApiService("https://example.test/", client)
        val result = api.renameAccountProfile(AccountProfileRenameDto("新名称", "原名称"))
        assertEquals("新名称", result.displayName)
        val (request, body) = sent.single()
        assertEquals("POST", request.method)
        assertEquals("/api/settings/account", request.url.encodedPath)
        assertEquals("Bearer own-session", request.header("Authorization"))
        assertNull(request.header(TICKETBOX_CURRENCY_BINDING_HEADER))
        assertEquals("""{"display_name":"新名称","expected_name":"原名称"}""", body)
    }
}

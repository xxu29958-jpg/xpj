package com.ticketbox.data.remote

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import kotlin.test.Test
import kotlin.test.assertEquals

class ApiClientDebtActivityCompatibilityTest {
    @Test fun absentCapabilityBlocksActivityDespiteMatchingApiVersion() = checkCapability(null, false)
    @Test fun unsupportedCapabilityVersionBlocksActivity() = checkCapability(2, false)
    @Test fun supportedCapabilityPreservesActivityRead() = checkCapability(1, true)

    private fun checkCapability(version: Int?, supported: Boolean) {
        val sent = mutableListOf<String>()
        val client = buildApiHttpClient(null, { "test-session" }, { "owner" }, null, null)
            .newBuilder().addInterceptor { chain ->
                val request = chain.request()
                sent += request.url.encodedPath
                val capability = version?.let { "\"debt_activity_read_version\":$it," }.orEmpty()
                val json = if (request.url.encodedPath == "/api/system/runtime-compatibility") {
                    """{"api_version":"$CURRENT_TICKETBOX_API_VERSION","write_compatibility":"compatible",
                        "capabilities":{$capability"currency":{"request_binding":"1:1:CNY"}}}"""
                } else "{}"
                Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(200)
                    .message("Controlled response")
                    .body(json.toResponseBody("application/json".toMediaType())).build()
            }.build()

        client.newCall(Request.Builder().url("https://example.test/api/debts/debt-1/activity?page=1").build())
            .execute().use { response ->
                assertEquals(if (supported) 200 else 409, response.code)
                if (!supported) {
                    assertEquals(true, response.body.string().contains("runtime_version_mismatch"))
                }
            }

        assertEquals(
            if (supported) listOf("/api/system/runtime-compatibility", "/api/debts/debt-1/activity")
            else listOf("/api/system/runtime-compatibility"),
            sent,
        )
    }
}

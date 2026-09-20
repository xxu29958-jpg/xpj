package com.ticketbox.data.remote

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Test
import kotlin.test.assertEquals

class ApiClientOriginalCapabilityTest {
    @Test fun absentFeatureBlocksOriginalRoutesDespiteMatchingApiVersion() = checkFeature(null, false)
    @Test fun unsupportedFeatureVersionBlocksOriginalRoutes() = checkFeature(2, false)
    @Test fun supportedFeaturePreservesOriginalRoutes() = checkFeature(1, true)

    private fun checkFeature(version: Int?, supported: Boolean) {
        val paths = listOf("original", "original/verify", "original/replenish", "original/cleanup/retry", "original/cleanup/cancel")
        for (path in paths) {
            val sent = mutableListOf<String>()
            val client = buildApiHttpClient(null, { "test-session" }, { "owner" }, null, null)
                .newBuilder().addInterceptor { chain ->
                    val request = chain.request()
                    sent += request.url.encodedPath
                    val feature = version?.let { "\"original_attachment_version\":$it," }.orEmpty()
                    val json = if (request.url.encodedPath == "/api/system/runtime-compatibility") {
                        """{"api_version":"$CURRENT_TICKETBOX_API_VERSION","write_compatibility":"compatible",
                            "capabilities":{$feature"currency":{"request_binding":"1:1:CNY"}}}"""
                    } else "{}"
                    Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(200).message("Controlled response")
                        .body(json.toResponseBody("application/json".toMediaType())).build()
                }.build()
            val builder = Request.Builder().url("https://example.test/api/expenses/7/$path")
                .header(TICKETBOX_API_VERSION_HEADER, CURRENT_TICKETBOX_API_VERSION)
            if (path != "original") builder.post("{}".toRequestBody("application/json".toMediaType()))
            client.newCall(builder.build()).execute().use { response ->
                assertEquals(if (supported) 200 else 409, response.code, path)
            }
            assertEquals(if (supported) listOf("/api/system/runtime-compatibility", "/api/expenses/7/$path")
                else listOf("/api/system/runtime-compatibility"), sent)
        }
    }
}

package com.ticketbox.data.remote

import com.ticketbox.data.remote.dto.PaymentCaptureBatchCreateDto
import com.ticketbox.data.remote.dto.PaymentCaptureCreateDto
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import kotlin.test.Test
import kotlin.test.assertEquals

class ApiClientNotificationBatchTest {
    @Test fun batchRequiresDeclaredCapabilityWithoutSendingAPartialLegacyRequest() = runBlocking {
        for (version in listOf(null, 1, 2)) {
            var writes = 0
            val http = buildApiHttpClient(null, { "session" }, { "owner" }, null, null).newBuilder()
                .addInterceptor { chain ->
                    val request = chain.request()
                    val runtime = request.url.encodedPath == "/api/system/runtime-compatibility"
                    if (!runtime) writes++
                    val capability = version?.let { "\"notification_batch_version\":$it," }.orEmpty()
                    val body = if (runtime) """{"api_version":"$CURRENT_TICKETBOX_API_VERSION","write_compatibility":"compatible",
                        "capabilities":{$capability"currency":{"request_binding":"1:1:CNY"}}}""" else "{}"
                    Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(if (runtime) 200 else 400)
                        .message("Controlled transport").body(body.toResponseBody("application/json".toMediaType())).build()
                }.build()
            val captures = listOf(1000L, 1290L).mapIndexed { index, amount -> PaymentCaptureCreateDto(
                "event-$index", "alipay", "2026-11-01T09:49:00Z", "CNY", amount, null, "expense", "v5", emptyList()) }
            val error = runCatching { buildApiService("https://example.test/", http).capturePayments(
                PaymentCaptureBatchCreateDto(captures)) }.exceptionOrNull() as HttpException
            assertEquals(if (version == 1) 400 else 409, error.code())
            assertEquals(if (version == 1) 1 else 0, writes)
        }
    }
}

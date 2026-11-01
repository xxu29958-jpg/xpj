package com.ticketbox.data.remote

import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import retrofit2.HttpException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ApiClientConfirmationCompatibilityTest {
    @Test fun atomicConfirmationNeverDegradesToLegacyPartialSave() = runBlocking {
        for (version in listOf(null, 1, 2)) for (withChanges in listOf(false, true)) {
            val writes = mutableListOf<String>()
            val http = buildApiHttpClient(null, { "session" }, { "owner" }, null, null).newBuilder()
                .addInterceptor { chain ->
                    val request = chain.request()
                    val runtime = request.url.encodedPath == "/api/system/runtime-compatibility"
                    if (!runtime) writes += Buffer().also { requireNotNull(request.body).writeTo(it) }.readUtf8()
                    val capability = version?.let { "\"expense_confirmation_version\":$it," }.orEmpty()
                    val body = if (runtime) """{"api_version":"$CURRENT_TICKETBOX_API_VERSION","write_compatibility":"compatible",
                        "capabilities":{$capability"currency":{"request_binding":"1:1:CNY"}}}""" else "{}"
                    Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(if (runtime) 200 else 400)
                        .message("Controlled transport").body(body.toResponseBody("application/json".toMediaType())).build()
                }.build()
            val changes = ExpenseUpdateRequest(merchant = "Original", category = null, note = "preserved",
                expenseTime = null, tags = null, valueScore = null, regretScore = null)
            val error = runCatching { buildApiService("https://example.test/", http).confirmExpense("9",
                ExpenseStateTokenRequest(7, changes = changes.takeIf { withChanges }), "original-key") }.exceptionOrNull() as HttpException
            val allowed = !withChanges || version == 2
            assertEquals(if (allowed) 400 else 409, error.code())
            assertEquals(if (allowed) 1 else 0, writes.size)
            if (withChanges && allowed) assertTrue(writes.single().contains("preserved"))
        }
    }
}

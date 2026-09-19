package com.ticketbox.data.remote

import com.ticketbox.data.remote.dto.CorrectionOptionalTimeInput
import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseTimeInputDto
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import retrofit2.HttpException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ApiClientAccountingTimeCompatibilityTest {
    @Test fun onlyCommandsWithNewTimeMeaningRequireTheDeclaredCapability() = runBlocking {
        for (version in listOf(null, 1, 2)) for (kind in listOf("create", "patch", "correction")) {
            for (withTime in listOf(false, true)) for (preVersioned in listOf(false, true)) {
                verifyCommand(version, kind, withTime, preVersioned)
            }
        }
    }

    private suspend fun verifyCommand(version: Int?, kind: String, withTime: Boolean, preVersioned: Boolean) {
        val writes = mutableListOf<Pair<Request, String>>()
        val client = buildApiHttpClient(null, { "test-session" }, { "owner" }, null, null).newBuilder()
        if (preVersioned) client.interceptors().add(0, okhttp3.Interceptor { chain ->
            chain.proceed(chain.request().newBuilder().header(TICKETBOX_API_VERSION_HEADER, CURRENT_TICKETBOX_API_VERSION).build())
        })
        client.addInterceptor { chain ->
            val request = chain.request()
            val runtime = request.url.encodedPath == "/api/system/runtime-compatibility"
            if (!runtime) writes += request to Buffer().also { requireNotNull(request.body).writeTo(it) }.readUtf8()
            Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(if (runtime) 200 else 400)
                .message("Controlled transport result")
                .body((if (runtime) runtimeJson(version) else "{}").toResponseBody("application/json".toMediaType())).build()
        }
        val api = buildApiService("https://example.test/", client.build())
        val error = runCatching { send(api, kind, withTime) }.exceptionOrNull() as HttpException
        val allowed = !withTime || version == 1
        assertEquals(if (allowed) 400 else 409, error.code(), "$version/$kind/$withTime/$preVersioned")
        assertEquals(if (allowed) 1 else 0, writes.size)
        writes.forEach { (request, body) ->
            assertEquals("owner", request.header(LEDGER_ID_HEADER))
            assertEquals("Bearer test-session", request.header("Authorization"))
            assertEquals(withTime, body.contains("\"time_input\""))
            if (kind == "create") assertTrue(body.contains("original-ref"))
            else assertEquals("original-key", request.header("Idempotency-Key"))
        }
    }

    private suspend fun send(api: ApiService, kind: String, withTime: Boolean) {
        val time = if (withTime) ExpenseTimeInputDto("date_only", 3, "2026-05-01") else null
        when (kind) {
            "create" -> api.createManualExpense(ExpenseManualCreateRequestDto(
                merchant = "Original", category = "其他", note = null, expenseTime = null, tags = null,
                valueScore = null, regretScore = null, clientRef = "original-ref", timeInput = time))
            "patch" -> api.updateExpense("9", ExpenseUpdateRequest(
                expectedRowVersion = 7, merchant = null, category = null, note = "Original", expenseTime = null,
                tags = null, valueScore = null, regretScore = null, timeInput = time), "original-key")
            "correction" -> api.correctExpense("9", ExpenseCorrectionRequestDto(7, "Original",
                timeInput = time?.let(CorrectionOptionalTimeInput::changed) ?: CorrectionOptionalTimeInput.unchanged()), "original-key")
        }
    }

    private fun runtimeJson(version: Int?): String {
        val capability = version?.let { "\"accounting_time_input_version\":$it," }.orEmpty()
        return """{"api_version":"$CURRENT_TICKETBOX_API_VERSION","write_compatibility":"compatible",
            "capabilities":{$capability"currency":{"request_binding":"1:1:CNY"}}}"""
    }
}

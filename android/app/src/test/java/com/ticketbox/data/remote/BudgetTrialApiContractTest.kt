package com.ticketbox.data.remote

import com.ticketbox.data.remote.dto.BudgetAdviseRequestDto
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class BudgetTrialApiContractTest {
    @Test fun trialAndAiCarryReportAndOriginalCurrencyWithExactMinorUnitsAndLegacySourceOmission() = runBlocking {
        val observed = mutableListOf<Request>()
        val bodies = mutableListOf<String>()
        val client = OkHttpClient.Builder().addInterceptor { chain ->
            val request = chain.request()
            observed += request
            bodies += request.body?.let { Buffer().also(it::writeTo).readUtf8() }.orEmpty()
            val basis = """{"month":"2026-09","home_currency_code":"USD","breakdown":{"monthly_income_cents":10000,"fixed_expenses_cents":1000,"spent_amount_cents":2000,"savings_target_cents":240,"reserved_buffer_cents":30,"discretionary_cents":6730},"missing_rates":[],"is_trial":true}"""
            val response = if (request.method == "POST")
                """{"advice":null,"provider_name":"fixture","home_currency_code":"USD","inputs":$basis}""" else basis
            Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(200).message("Controlled response")
                .body(response.toResponseBody("application/json".toMediaType())).build()
        }.build()
        val api = buildApiService("https://example.test/", client)
        api.trialBudgetAdviceInputs("2026-09", "Asia/Shanghai", mapOf("home_currency_code" to "USD",
            "arrangement_currency_code" to "JPY", "savings_target_cents" to "5000000000", "reserved_buffer_cents" to "300"))
        api.budgetAdvise(BudgetAdviseRequestDto("2026-09", "Asia/Shanghai", "USD", 5_000_000_000, 300, "JPY"))
        api.trialBudgetAdviceInputs("2026-09", "Asia/Shanghai", mapOf("home_currency_code" to "JPY",
            "savings_target_cents" to "2400", "reserved_buffer_cents" to "300"))
        assertEquals("/api/budget/advisor/inputs", observed[0].url.encodedPath)
        assertEquals("2026-09", observed[0].url.queryParameter("month"))
        assertEquals("Asia/Shanghai", observed[0].url.queryParameter("timezone"))
        assertEquals("USD", observed[0].url.queryParameter("home_currency_code"))
        assertEquals("JPY", observed[0].url.queryParameter("arrangement_currency_code"))
        assertEquals("5000000000", observed[0].url.queryParameter("savings_target_cents"))
        assertEquals("300", observed[0].url.queryParameter("reserved_buffer_cents"))
        assertEquals("/api/budget/advise", observed[1].url.encodedPath)
        assertTrue(bodies[1].contains("\"home_currency_code\":\"USD\""))
        assertTrue(bodies[1].contains("\"arrangement_currency_code\":\"JPY\""))
        assertTrue(bodies[1].contains("\"savings_target_cents\":5000000000"))
        assertNull(observed[2].url.queryParameter("arrangement_currency_code"))
        observed.forEach { assertNull(it.header("Idempotency-Key")) }
    }
}

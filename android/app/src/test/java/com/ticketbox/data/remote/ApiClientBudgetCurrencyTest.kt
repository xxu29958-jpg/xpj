package com.ticketbox.data.remote

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import kotlin.test.Test
import kotlin.test.assertTrue

class ApiClientBudgetCurrencyTest {
    @Test
    fun unconfiguredBudgetTransmitsExplicitNullVersionAndCapturedCurrency() = runTest {
        var sent = ""
        val client = OkHttpClient.Builder().addInterceptor { chain ->
            val buffer = Buffer()
            chain.request().body!!.writeTo(buffer)
            sent = buffer.readUtf8()
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1)
                .code(422).message("Refused").body("{}".toResponseBody()).build()
        }.build()
            val api = buildApiService("https://example.test/", client)
            val request = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
                .adapter(BudgetMonthlyUpdateRequestDto::class.java).fromJson(
                    """{"home_currency_code":"JPY","expected_row_version":null,"total_amount_cents":1200}""",
                )!!
            runCatching { api.updateMonthlyBudget("2026-09", request, "UTC") }
            assertTrue(sent.contains("\"home_currency_code\":\"JPY\""), sent)
            assertTrue(sent.contains("\"expected_row_version\":null"), sent)
            assertTrue(sent.contains("\"total_amount_cents\":1200"), sent)
    }
}

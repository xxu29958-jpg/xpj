package com.ticketbox.data.remote

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import kotlinx.coroutines.test.runTest
import okhttp3.OkHttpClient
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import kotlin.test.Test
import kotlin.test.assertTrue

class ApiClientBudgetCurrencyTest {
    @Test
    fun unconfiguredBudgetTransmitsExplicitNullVersionAndCapturedCurrency() = runTest {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setResponseCode(422).setBody("{}"))
            val api = buildApiService(server.url("/").toString(), OkHttpClient())
            val request = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
                .adapter(BudgetMonthlyUpdateRequestDto::class.java).fromJson(
                    """{"home_currency_code":"JPY","expected_row_version":null,"total_amount_cents":1200}""",
                )!!
            runCatching { api.updateMonthlyBudget("2026-09", request, "UTC") }
            val sent = server.takeRequest().body.readUtf8()
            assertTrue(sent.contains("\"home_currency_code\":\"JPY\""), sent)
            assertTrue(sent.contains("\"expected_row_version\":null"), sent)
            assertTrue(sent.contains("\"total_amount_cents\":1200"), sent)
        }
    }
}

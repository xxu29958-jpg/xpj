package com.ticketbox.data.remote

import com.ticketbox.data.repository.NetworkErrorHandler
import com.ticketbox.data.repository.RepositoryException
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class ApiClientIncomeReadCompatibilityTest {
    @Test
    fun olderIncomeResponseGivesUpgradeGuidanceBeforeMoshiDecoding() = runTest {
        val requests = mutableListOf<String>()
        val api = incomeReadApi(requests, "2026-08-02")
        val errors = NetworkErrorHandler({ null }, "IncomePlan")

        val result = errors.safeCall { api.listIncomePlans("active") }

        val error = result.exceptionOrNull() as RepositoryException
        assertEquals("runtime_version_mismatch", error.errorCode)
        assertTrue(error.message.orEmpty().contains("配套版本"))
        assertEquals(listOf("/api/system/runtime-compatibility"), requests)
    }

    @Test
    fun currentIncomeReadDoesNotRequireWritePermissionOrCurrencyBinding() = runTest {
        for (conclusion in listOf("read_only", "owner_action_required")) {
            val requests = mutableListOf<String>()
            val api = incomeReadApi(requests, CURRENT_TICKETBOX_API_VERSION, conclusion)

            val response = api.listIncomePlans("archived")

            assertEquals("2026-02", response.month)
            assertEquals(10000L, response.expectedAmountCents)
            assertEquals(0L, response.totalActiveAmountCents)
            assertEquals(0L, response.scheduledAmountCents)
            assertEquals(listOf("/api/system/runtime-compatibility", "/api/income-plans"), requests)
        }
    }
}

private fun incomeReadApi(requests: MutableList<String>, version: String, conclusion: String = "read_only"): ApiService {
    val client = buildApiHttpClient(null, { "test-session" }, { "owner" }, null, null)
        .newBuilder().addInterceptor { chain ->
            val request = chain.request()
            requests += request.url.encodedPath
            val body = if (request.url.encodedPath == "/api/system/runtime-compatibility") {
                """{"api_version":"$version","write_compatibility":"$conclusion","capabilities":{"currency":{"request_binding":null}}}"""
            } else if (version == CURRENT_TICKETBOX_API_VERSION) {
                """{"items":[],"total_active_amount_cents":0,"expected_amount_cents":10000,"month":"2026-02","scheduled_amount_cents":0,"effective_plan_count":1}"""
            } else {
                """{"items":[],"total_active_amount_cents":0}"""
            }
            Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(200).message("OK")
                .body(body.toResponseBody("application/json".toMediaType())).build()
        }.build()
    return buildApiService("https://example.test/", client)
}

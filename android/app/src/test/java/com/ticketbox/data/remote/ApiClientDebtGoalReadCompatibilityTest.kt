package com.ticketbox.data.remote

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import kotlin.test.Test
import kotlin.test.assertEquals

class ApiClientDebtGoalReadCompatibilityTest {
    @Test fun newlyClearedGoalListAndDetailCarryObservedBindingForAchievement() {
        for (path in listOf("/api/goals?goal_type=debt_repayment", "/api/goals/linked-goal")) {
            checkRead(path, conclusion = "compatible", binding = "1:7:CNY", status = 200)
        }
    }

    @Test fun viewerCanStillReadAchievementWithoutWriterCapability() {
        checkRead("/api/goals?goal_type=debt_repayment", "read_only", null, 200)
        checkRead("/api/goals/linked-goal", "read_only", null, 200)
    }

    @Test fun changedBindingRefusalIsReturnedWithoutReplayingAchievementRead() {
        checkRead("/api/goals/linked-goal", "compatible", "1:7:CNY", 409)
    }

    private fun checkRead(path: String, conclusion: String, binding: String?, status: Int) {
        val sent = mutableListOf<String>()
        val client = buildApiHttpClient(null, { "goal-reader" }, { "receiver-ledger" }, null, null)
            .newBuilder().addInterceptor { chain ->
                val request = chain.request()
                sent += request.url.encodedPath
                assertEquals("Bearer goal-reader", request.header("Authorization"))
                assertEquals("receiver-ledger", request.header(LEDGER_ID_HEADER))
                val negotiation = request.url.encodedPath == "/api/system/runtime-compatibility"
                val json = if (negotiation) {
                    val wireBinding = binding?.let { "\"$it\"" } ?: "null"
                    """{"api_version":"$CURRENT_TICKETBOX_API_VERSION","write_compatibility":"$conclusion",
                        "capabilities":{"currency":{"request_binding":$wireBinding}}}"""
                } else {
                    assertEquals(CURRENT_TICKETBOX_API_VERSION, request.header(TICKETBOX_API_VERSION_HEADER))
                    assertEquals(binding, request.header(TICKETBOX_CURRENCY_BINDING_HEADER))
                    if (status == 200) """{"evaluation_state":"achieved","achieved_version":1}"""
                    else """{"error":"currency_binding_revision_conflict"}"""
                }
                Response.Builder().request(request).protocol(Protocol.HTTP_1_1)
                    .code(if (negotiation) 200 else status).message("Controlled response")
                    .body(json.toResponseBody("application/json".toMediaType())).build()
            }.build()

        client.newCall(Request.Builder().url("https://example.test$path").build()).execute().use {
            assertEquals(status, it.code)
            assertEquals(if (status == 200) """{"evaluation_state":"achieved","achieved_version":1}"""
                else """{"error":"currency_binding_revision_conflict"}""", it.body.string())
        }
        assertEquals(listOf("/api/system/runtime-compatibility", path.substringBefore('?')), sent)
    }
}

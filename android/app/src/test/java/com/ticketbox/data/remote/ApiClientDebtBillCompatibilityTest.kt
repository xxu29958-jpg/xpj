package com.ticketbox.data.remote

import com.ticketbox.data.remote.api.DebtApi
import com.ticketbox.data.remote.dto.DebtBillSourceReferenceDto
import com.ticketbox.data.remote.dto.DebtCreateRequestDto
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.Invocation
import kotlin.test.Test
import kotlin.test.assertEquals

class ApiClientDebtBillCompatibilityTest {
    @Test fun captureWithoutTheNewCapabilityIsExplicitlyRefused() = verify("/api/debt-bills", null, null, false)
    @Test fun captureWithTheNegotiatedCapabilityCanReachItsCommand() = verify("/api/debt-bills", 1, null, true)
    @Test fun sourceBearingCreateUsesTypedInvocationAndDoesNotGloballyBlockOldCreate() {
        verify("/api/debts", null, sourceRequest(), false)
        verify("/api/debts", 2, sourceRequest(), false)
        verify("/api/debts", 1, sourceRequest(), true)
        verify("/api/debts", null, sourceRequest().copy(billSource = null), true)
    }

    private fun sourceRequest() = DebtCreateRequestDto(homeCurrencyCode = "CNY", direction = "i_owe",
        counterpartyType = "external", counterpartyLabel = "Bank", principalAmountCents = 100,
        billSource = DebtBillSourceReferenceDto("source", 3))

    private fun verify(path: String, version: Int?, body: DebtCreateRequestDto?, allowed: Boolean) {
        val sent = mutableListOf<String>()
        val client = buildApiHttpClient(null, { "session" }, { "owner" }, null, null).newBuilder()
            .addInterceptor { chain ->
                val request = chain.request()
                sent += request.url.encodedPath
                val capability = version?.let { "\"debt_bill_source_version\":$it," }.orEmpty()
                val json = if (request.url.encodedPath == "/api/system/runtime-compatibility") {
                    """{"api_version":"$CURRENT_TICKETBOX_API_VERSION","write_compatibility":"compatible",
                        "capabilities":{$capability"currency":{"request_binding":"1:1:CNY"}}}"""
                } else "{}"
                Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(200).message("controlled")
                    .body(json.toResponseBody("application/json".toMediaType())).build()
            }.build()
        val request = Request.Builder().url("https://example.test$path").post("frozen bytes".toRequestBody())
        body?.let { dto -> request.tag(Invocation::class.java,
            Invocation.of(DebtApi::class.java.methods.single { it.name == "createDebt" }, listOf(dto, "original-key"))) }
        client.newCall(request.build()).execute().use { assertEquals(if (allowed) 200 else 409, it.code) }
        assertEquals(if (allowed) listOf("/api/system/runtime-compatibility", path)
            else listOf("/api/system/runtime-compatibility"), sent)
    }
}

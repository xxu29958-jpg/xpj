package com.ticketbox.data.remote

import com.ticketbox.data.remote.dto.IncomePlanCreateRequestDto
import com.ticketbox.data.remote.dto.IncomePlanTokenRequestDto
import com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto
import com.ticketbox.data.remote.dto.RecycleBinRestoreRequestDto
import com.ticketbox.data.repository.NetworkErrorHandler
import com.ticketbox.data.repository.RepositoryException
import kotlinx.coroutines.test.runTest
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertTrue

class ApiClientIncomeAdoptionTest {
    @Test
    fun currentAdoptionGivesOwnerGuidanceForEveryIncomeCommand() = runTest {
        for (command in incomeAdoptionCommands) {
            val transport = AdoptionTransport()
            val errors = NetworkErrorHandler({ null }, "IncomePlan")

            val result = errors.safeCall { command.execute(transport.api) }

            val error = assertIs<RepositoryException>(result.exceptionOrNull(), command.name)
            assertEquals("currency_adoption_required", error.errorCode, command.name)
            assertEquals(ADOPTION_GUIDANCE, error.message, command.name)
            assertEquals(1, transport.mutations.size, command.name)
            assertEquals(CURRENT_TICKETBOX_API_VERSION,
                transport.mutations.single().header(TICKETBOX_API_VERSION_HEADER), command.name)
            transport.requests.forEach { request ->
                assertNull(request.header(TICKETBOX_CURRENCY_BINDING_HEADER), command.name)
                assertEquals("Bearer test-session", request.header("Authorization"), command.name)
                assertEquals("owner", request.header(LEDGER_ID_HEADER), command.name)
            }
        }
    }

    @Test
    fun olderProtocolStillRequiresUpgradeDuringAdoption() = runTest {
        val transport = AdoptionTransport(version = "2026-08-02")
        val errors = NetworkErrorHandler({ null }, "IncomePlan")

        val result = errors.safeCall { incomeAdoptionCommands.first().execute(transport.api) }

        val error = assertIs<RepositoryException>(result.exceptionOrNull())
        assertEquals("runtime_version_mismatch", error.errorCode)
        assertTrue(error.message.orEmpty().contains("配套版本"))
        assertTrue(transport.mutations.isEmpty())
    }

    @Test
    fun configurationRefusalKeepsTheRealBindingForEveryIncomeCommand() = runTest {
        for (command in incomeAdoptionCommands) {
            val transport = AdoptionTransport(conclusion = "configuration_required", requestBinding = "1:7:JPY",
                ownerRefusal = "currency_binding_configuration_drift")
            val errors = NetworkErrorHandler({ null }, "IncomePlan")

            val result = errors.safeCall { command.execute(transport.api) }

            val error = assertIs<RepositoryException>(result.exceptionOrNull(), command.name)
            assertEquals("currency_binding_configuration_drift", error.errorCode, command.name)
            assertEquals(DRIFT_GUIDANCE, error.message, command.name)
            assertEquals(1, transport.mutations.size, command.name)
            val request = transport.mutations.single()
            assertEquals(CURRENT_TICKETBOX_API_VERSION, request.header(TICKETBOX_API_VERSION_HEADER), command.name)
            assertEquals("1:7:JPY", request.header(TICKETBOX_CURRENCY_BINDING_HEADER), command.name)
            assertEquals("Bearer test-session", request.header("Authorization"), command.name)
            assertEquals("owner", request.header(LEDGER_ID_HEADER), command.name)
        }
    }

    @Test
    fun adoptionDoesNotReplaceIndependentSessionAndRecycleOwnerResults() = runTest {
        val sessionTransport = AdoptionTransport(responseCode = 200, responseBody = LEDGER_SWITCH_RESPONSE)

        val switched = sessionTransport.api.switchLedger("family")

        assertEquals("family", switched.ledger.ledgerId)
        assertEquals(1, sessionTransport.mutations.size)
        assertEquals("/api/ledgers/family/switch", sessionTransport.mutations.single().url.encodedPath)
        val recycleTransport = AdoptionTransport(responseCode = 403,
            responseBody = """{"error":"permission_denied","message":"read only"}""")
        val errors = NetworkErrorHandler({ null }, "RecycleBin")

        val result = errors.safeCall {
            recycleTransport.api.restoreRecycleBinItem(RecycleBinRestoreRequestDto("category_rule", "1"))
        }

        assertEquals("permission_denied", assertIs<RepositoryException>(result.exceptionOrNull()).errorCode)
        assertEquals(1, recycleTransport.mutations.size)
        (sessionTransport.requests + recycleTransport.requests).forEach { request ->
            assertNull(request.header(TICKETBOX_CURRENCY_BINDING_HEADER))
        }
    }
}

private data class IncomeAdoptionCommand(val name: String, val execute: suspend (ApiService) -> Unit)

private val incomeAdoptionCommands = listOf(
    IncomeAdoptionCommand("create") { api ->
        api.createIncomePlan(IncomePlanCreateRequestDto("2026-09", "工资", "salary", amountCents = 10000, payDay = 15, homeCurrencyCode = "CNY"), "synthetic-income-create-key")
    },
    IncomeAdoptionCommand("edit") { api ->
        api.updateIncomePlan("plan-1", IncomePlanUpdateRequestDto("2026-09", 7, amountCents = 12000), "original-key")
    },
    IncomeAdoptionCommand("archive") { api ->
        api.archiveIncomePlan("plan-1", IncomePlanTokenRequestDto(7, "2026-09"))
    },
    IncomeAdoptionCommand("restore") { api ->
        api.restoreIncomePlan("plan-1", IncomePlanTokenRequestDto(7, "2026-09"))
    },
    IncomeAdoptionCommand("recycle restore") { api ->
        api.restoreRecycleBinItem(RecycleBinRestoreRequestDto("income_plan", "plan-1", 7, "2026-09"))
    },
    IncomeAdoptionCommand("normalized recycle restore") { api ->
        api.restoreRecycleBinItem(RecycleBinRestoreRequestDto(" income_plan ", "plan-1", 7, "2026-09"))
    },
)

/** Real auth, negotiation and Retrofit; only the HTTP transport is replaced. */
private class AdoptionTransport(
    private val version: String = CURRENT_TICKETBOX_API_VERSION,
    private val responseCode: Int = 409,
    private val responseBody: String = """{"error":"client_upgrade_required","message":"upgrade required"}""",
    private val conclusion: String = "owner_action_required",
    private val requestBinding: String? = null,
    private val ownerRefusal: String = "currency_adoption_required",
) {
    val requests = mutableListOf<Request>()
    val mutations: List<Request> get() = requests.filter { it.method != "GET" }
    val api: ApiService = buildApiService("https://example.test/",
        buildApiHttpClient(null, { "test-session" }, { "owner" }, null, null)
            .newBuilder().addInterceptor(::respond).build())

    private fun respond(chain: Interceptor.Chain): Response {
        val request = chain.request()
        requests += request
        val negotiating = request.url.encodedPath == "/api/system/runtime-compatibility"
        val body = if (negotiating) {
            val bindingJson = requestBinding?.let { "\"$it\"" } ?: "null"
            """{"api_version":"$version","write_compatibility":"$conclusion","capabilities":{"currency":{"request_binding":$bindingJson}}}"""
        } else if (responseCode == 409 && request.header(TICKETBOX_API_VERSION_HEADER) == CURRENT_TICKETBOX_API_VERSION &&
            request.header(TICKETBOX_CURRENCY_BINDING_HEADER) == requestBinding
        ) {
            // This is the required currency-owner precedence, separately exercised
            // against real backend code in test_income_protocol_boundary.py.
            val message = if (ownerRefusal == "currency_binding_configuration_drift") DRIFT_GUIDANCE else "Owner confirmation required."
            """{"error":"$ownerRefusal","message":"$message"}"""
        } else {
            // The current Income epoch guard rejects headerless commands.
            responseBody
        }
        return Response.Builder().request(request).protocol(Protocol.HTTP_1_1)
            .code(if (negotiating) 200 else responseCode).message("Synthetic response")
            .body(body.toResponseBody("application/json".toMediaType())).build()
    }
}

private const val ADOPTION_GUIDANCE =
    "这台小票夹正在等待安装拥有者在电脑端确认本位币。你的草稿和待同步操作会保留，确认后请重试。"
private const val DRIFT_GUIDANCE = "服务端币种配置与已持久化的本位币绑定不一致，已停止写入。"
private const val LEDGER_SWITCH_RESPONSE =
    """{"session_token":"test-session","ledger":{"ledger_id":"family","name":"家庭","role":"owner","is_default":false,"created_at":null,"archived_at":null},"account_name":"我","device_name":"手机"}"""

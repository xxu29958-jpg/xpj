package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.DebtCreateRequestDto
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.DebtListResponseDto
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtSourceTypes
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import java.lang.reflect.InvocationHandler
import java.lang.reflect.Method
import java.lang.reflect.Proxy
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class DebtRepositoryTest {

    @Test
    fun listDebtsMapsDomainModels() = runTest {
        val handler = DebtApiHandler().apply {
            debtsResult = DebtListResponseDto(items = listOf(debtDto(publicId = "d1", remaining = 4_200L)))
        }

        val debts = repository(handler).listDebts().getOrThrow()

        assertEquals(1, debts.size)
        assertEquals("d1", debts.single().publicId)
        assertEquals(4_200L, debts.single().remainingAmountCents)
        assertTrue(debts.single().isExternal)
    }

    @Test
    fun createDebtSendsExternalManualPayloadWithIdempotencyKey() = runTest {
        val handler = DebtApiHandler()

        val created = repository(handler).createDebt(
            DebtDraft(
                direction = DebtDirections.I_OWE,
                counterpartyLabel = "  房东  ",
                principalAmountCents = 50_000,
            ),
        ).getOrThrow()

        val call = handler.createCalls.single()
        assertEquals(DebtDirections.I_OWE, call.request.direction)
        assertEquals(DebtCounterpartyTypes.EXTERNAL, call.request.counterpartyType)
        assertEquals(DebtSourceTypes.MANUAL, call.request.sourceType)
        // The repository trims the label before the request leaves the client.
        assertEquals("房东", call.request.counterpartyLabel)
        assertEquals(50_000L, call.request.principalAmountCents)
        // ADR-0042: a fresh single-use intent key per direct call.
        assertTrue(!call.idempotencyKey.isNullOrBlank())
        assertEquals("created", created.publicId)
    }

    @Test
    fun createDebtMintsAFreshIdempotencyKeyPerCall() = runTest {
        val handler = DebtApiHandler()
        val repository = repository(handler)
        val draft = DebtDraft(DebtDirections.I_OWE, "房东", 50_000)

        repository.createDebt(draft).getOrThrow()
        repository.createDebt(draft).getOrThrow()

        // ADR-0042: each direct create is a distinct single-use intent — keys must NOT be reused.
        val keys = handler.createCalls.mapNotNull { it.idempotencyKey }
        assertEquals(2, keys.size)
        assertEquals(2, keys.toSet().size)
    }

    @Test
    fun viewerCreateShortCircuitsWithoutApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler, viewerSettingsStore())
            .createDebt(DebtDraft(DebtDirections.I_OWE, "房东", 50_000))

        assertTrue(result.isFailure)
        assertEquals("当前角色为只读，无法修改账本。", result.exceptionOrNull()?.message)
        assertTrue(handler.createCalls.isEmpty())
    }

    @Test
    fun createRejectsBlankCounterpartyBeforeApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler).createDebt(DebtDraft(DebtDirections.I_OWE, "   ", 50_000))

        assertTrue(result.isFailure)
        assertTrue(handler.createCalls.isEmpty())
    }

    @Test
    fun createRejectsNonPositiveAmountBeforeApiCall() = runTest {
        val handler = DebtApiHandler()

        val result = repository(handler).createDebt(DebtDraft(DebtDirections.I_OWE, "房东", 0))

        assertTrue(result.isFailure)
        assertTrue(handler.createCalls.isEmpty())
    }

    @Test
    fun listDebtsErrorSurfacesAsFailure() = runTest {
        val handler = DebtApiHandler().apply {
            debtsError = HttpException(
                Response.error<DebtListResponseDto>(
                    404,
                    """{"error":"not_found","message":"没有找到这笔欠款。"}"""
                        .toResponseBody("application/json".toMediaType()),
                ),
            )
        }

        val result = repository(handler).listDebts()

        assertTrue(result.isFailure)
    }

    private fun repository(
        handler: DebtApiHandler,
        settings: FakeTicketboxSettingsStore = boundSettingsStore(),
    ): DebtRepository {
        val tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") }
        return DebtRepository(
            apiClient = DebtApiFactory(handler),
            settingsStore = settings,
            tokenStore = tokenStore,
        )
    }

    private fun viewerSettingsStore(): FakeTicketboxSettingsStore =
        FakeTicketboxSettingsStore().apply {
            saveServerUrl("https://api.example.com")
            saveIdentity(
                accountName = "我",
                ledgerId = "owner",
                ledgerName = "我的小票夹",
                deviceName = "Pixel",
                role = "viewer",
                boundAt = "2026-05-01T00:00:00Z",
            )
        }
}

private fun debtDto(publicId: String = "debt-1", remaining: Long = 30_000L): DebtDto = DebtDto(
    publicId = publicId,
    ledgerId = "owner",
    direction = DebtDirections.I_OWE,
    counterpartyType = DebtCounterpartyTypes.EXTERNAL,
    counterpartyAccountId = null,
    counterpartyLabel = "房东",
    principalAmountCents = 50_000,
    remainingAmountCents = remaining,
    paidAmountCents = 50_000 - remaining,
    status = DebtLinkStatuses.OPEN,
    sourceType = DebtSourceTypes.MANUAL,
    sourceId = null,
    homeCurrencyCode = "CNY",
    createdAt = "2026-06-15T00:00:00Z",
    updatedAt = "2026-06-15T00:00:00Z",
    rowVersion = 1,
)

private class DebtApiFactory(private val handler: DebtApiHandler) : ApiServiceFactory {
    override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = handler.service()
}

private data class CreateDebtCall(val request: DebtCreateRequestDto, val idempotencyKey: String?)

private class DebtApiHandler : InvocationHandler {
    val createCalls = mutableListOf<CreateDebtCall>()
    var debtsResult: DebtListResponseDto? = null
    var debtsError: Throwable? = null

    fun service(): ApiService = Proxy.newProxyInstance(
        ApiService::class.java.classLoader,
        arrayOf(ApiService::class.java),
        this,
    ) as ApiService

    override fun invoke(proxy: Any, method: Method, args: Array<out Any?>?): Any? {
        if (method.declaringClass == Any::class.java) {
            return when (method.name) {
                "toString" -> "DebtApiProxy"
                "hashCode" -> System.identityHashCode(proxy)
                "equals" -> proxy === args?.firstOrNull()
                else -> null
            }
        }
        // Suspend methods arrive with a trailing Continuation; real params are the leading ones.
        val values = args.orEmpty()
        return when (method.name) {
            "debts" -> {
                debtsError?.let { throw it }
                debtsResult ?: DebtListResponseDto(items = listOf(debtDto()))
            }
            "createDebt" -> {
                createCalls += CreateDebtCall(
                    request = values[0] as DebtCreateRequestDto,
                    idempotencyKey = values[1] as String?,
                )
                debtDto(publicId = "created")
            }
            else -> error("unexpected ApiService call: ${method.name}")
        }
    }
}

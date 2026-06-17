package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.RepaymentDraftConfirmRequestDto
import com.ticketbox.data.remote.dto.RepaymentDraftCreateRequestDto
import com.ticketbox.data.remote.dto.RepaymentDraftDto
import com.ticketbox.data.remote.dto.RepaymentDraftListResponseDto
import com.ticketbox.domain.model.RepaymentDraftSource
import com.ticketbox.domain.model.RepaymentDraftStatuses
import com.ticketbox.domain.model.RepaymentNotificationDraft
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

class RepaymentDraftRepositoryTest {

    @Test
    fun listPendingDraftsMapsDomainModelsAndPassesPendingStatus() = runTest {
        val handler = RepaymentDraftApiHandler().apply {
            listResult = RepaymentDraftListResponseDto(items = listOf(draftDto(publicId = "d1", amount = 50_000)))
        }

        val drafts = repository(handler).listPendingDrafts().getOrThrow()

        assertEquals(1, drafts.size)
        assertEquals("d1", drafts.single().publicId)
        assertEquals(50_000L, drafts.single().amountCents)
        assertTrue(drafts.single().isPending)
        // The inbox only ever lists pending drafts.
        assertEquals(RepaymentDraftStatuses.PENDING, handler.listCalls.single())
    }

    @Test
    fun listPendingDraftsErrorSurfacesAsFailure() = runTest {
        val handler = RepaymentDraftApiHandler().apply {
            listError = HttpException(
                Response.error<RepaymentDraftListResponseDto>(
                    500,
                    """{"error":"server_error","message":"x"}""".toResponseBody("application/json".toMediaType()),
                ),
            )
        }

        assertTrue(repository(handler).listPendingDrafts().isFailure)
    }

    @Test
    fun createDraftPostsCapturePayloadBoundToPostTimeLedger() = runTest {
        val handler = RepaymentDraftApiHandler()

        val created = repository(handler).createDraft(
            draft = RepaymentNotificationDraft(
                source = RepaymentDraftSource.Alipay,
                amountCents = 50_000,
                merchantLabel = "  花呗  ",
                capturedAt = "2026-06-17T08:00:00Z",
            ),
            expectedLedgerId = "owner",
            notificationKey = "key-1",
        ).getOrThrow()

        val call = handler.createCalls.single()
        assertEquals("alipay", call.source)
        assertEquals(50_000L, call.amountCents)
        // The repository trims the label before the request leaves the client.
        assertEquals("花呗", call.merchantLabel)
        assertEquals("2026-06-17T08:00:00Z", call.capturedAt)
        assertEquals("key-1", call.notificationKey)
        assertEquals("created", created.publicId)
    }

    @Test
    fun createDraftRejectedWhenLedgerSwitchedSincePost() = runTest {
        val handler = RepaymentDraftApiHandler()

        // The post-time ledger no longer matches the active ledger → reject rather than capture into
        // the wrong book (mirrors createNotificationDraft). The API must not be hit.
        val result = repository(handler).createDraft(
            draft = RepaymentNotificationDraft(RepaymentDraftSource.Alipay, 50_000, null, "2026-06-17T08:00:00Z"),
            expectedLedgerId = "another-ledger",
            notificationKey = "key-1",
        )

        assertTrue(result.isFailure)
        assertTrue(handler.createCalls.isEmpty())
    }

    @Test
    fun confirmDraftSendsTargetVersionAndKey() = runTest {
        val handler = RepaymentDraftApiHandler().apply {
            confirmResult = draftDto(publicId = "d1", status = RepaymentDraftStatuses.CONFIRMED)
        }

        val confirmed = repository(handler).confirmDraft(
            draftPublicId = "d1",
            targetDebtPublicId = "debt-9",
            expectedRowVersion = 3L,
        ).getOrThrow()

        val call = handler.confirmCalls.single()
        assertEquals("d1", call.publicId)
        assertEquals("debt-9", call.request.targetDebtPublicId)
        assertEquals(3L, call.request.expectedRowVersion)
        assertTrue(!call.idempotencyKey.isNullOrBlank())
        assertTrue(!confirmed.isPending)
    }

    @Test
    fun confirmDraftViewerShortCircuitsWithoutApiCall() = runTest {
        val handler = RepaymentDraftApiHandler()

        val result = repository(handler, viewerSettingsStore())
            .confirmDraft("d1", targetDebtPublicId = "debt-9", expectedRowVersion = 1L)

        assertTrue(result.isFailure)
        assertEquals("当前角色为只读，无法修改账本。", result.exceptionOrNull()?.message)
        assertTrue(handler.confirmCalls.isEmpty())
    }

    @Test
    fun confirmDraftMintsFreshKeyPerCall() = runTest {
        val handler = RepaymentDraftApiHandler()
        val repository = repository(handler)

        repository.confirmDraft("d1", targetDebtPublicId = "debt-9", expectedRowVersion = 1L).getOrThrow()
        repository.confirmDraft("d1", targetDebtPublicId = "debt-9", expectedRowVersion = 2L).getOrThrow()

        val keys = handler.confirmCalls.mapNotNull { it.idempotencyKey }
        assertEquals(2, keys.size)
        assertEquals(2, keys.toSet().size)
    }

    @Test
    fun dismissDraftSendsBodyAndMapsResult() = runTest {
        val handler = RepaymentDraftApiHandler().apply {
            dismissResult = draftDto(publicId = "d1", status = RepaymentDraftStatuses.DISMISSED)
        }

        val dismissed = repository(handler).dismissDraft("d1").getOrThrow()

        assertEquals("d1", handler.dismissCalls.single())
        assertTrue(!dismissed.isPending)
    }

    @Test
    fun dismissDraftViewerShortCircuitsWithoutApiCall() = runTest {
        val handler = RepaymentDraftApiHandler()

        val result = repository(handler, viewerSettingsStore()).dismissDraft("d1")

        assertTrue(result.isFailure)
        assertEquals("当前角色为只读，无法修改账本。", result.exceptionOrNull()?.message)
        assertTrue(handler.dismissCalls.isEmpty())
    }

    private fun repository(
        handler: RepaymentDraftApiHandler,
        settings: FakeTicketboxSettingsStore = boundSettingsStore(),
    ): RepaymentDraftRepository {
        val tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") }
        return RepaymentDraftRepository(
            apiClient = RepaymentDraftApiFactory(handler),
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

private fun draftDto(
    publicId: String = "draft-1",
    amount: Long = 50_000L,
    status: String = RepaymentDraftStatuses.PENDING,
): RepaymentDraftDto = RepaymentDraftDto(
    publicId = publicId,
    source = "alipay",
    amountCents = amount,
    homeCurrencyCode = "CNY",
    merchantLabel = "花呗",
    capturedAt = "2026-06-17T08:00:00Z",
    status = status,
    committedDebtPublicId = null,
    committedRepaymentPublicId = null,
    createdAt = "2026-06-17T08:00:01Z",
    resolvedAt = null,
)

private class RepaymentDraftApiFactory(private val handler: RepaymentDraftApiHandler) : ApiServiceFactory {
    override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = handler.service()
}

private data class CreateDraftCall(
    val source: String,
    val amountCents: Long,
    val merchantLabel: String?,
    val capturedAt: String?,
    val notificationKey: String?,
)

private data class ConfirmDraftCall(
    val publicId: String,
    val request: RepaymentDraftConfirmRequestDto,
    val idempotencyKey: String?,
)

private class RepaymentDraftApiHandler : InvocationHandler {
    val listCalls = mutableListOf<String?>()
    val createCalls = mutableListOf<CreateDraftCall>()
    val confirmCalls = mutableListOf<ConfirmDraftCall>()
    val dismissCalls = mutableListOf<String>()
    var listResult: RepaymentDraftListResponseDto? = null
    var listError: Throwable? = null
    var confirmResult: RepaymentDraftDto? = null
    var dismissResult: RepaymentDraftDto? = null

    fun service(): ApiService = Proxy.newProxyInstance(
        ApiService::class.java.classLoader,
        arrayOf(ApiService::class.java),
        this,
    ) as ApiService

    override fun invoke(proxy: Any, method: Method, args: Array<out Any?>?): Any? {
        if (method.declaringClass == Any::class.java) return objectMethod(proxy, method, args)
        // Suspend methods arrive with a trailing Continuation; real params are the leading ones.
        val values = args.orEmpty()
        return when (method.name) {
            "repaymentDrafts" -> {
                listError?.let { throw it }
                listCalls += values.getOrNull(0) as String?
                listResult ?: RepaymentDraftListResponseDto(items = listOf(draftDto()))
            }
            "createRepaymentDraft" -> {
                val request = values[0] as RepaymentDraftCreateRequestDto
                createCalls += CreateDraftCall(
                    source = request.source,
                    amountCents = request.amountCents,
                    merchantLabel = request.merchantLabel,
                    capturedAt = request.capturedAt,
                    notificationKey = request.notificationKey,
                )
                draftDto(publicId = "created")
            }
            "confirmRepaymentDraft" -> {
                confirmCalls += ConfirmDraftCall(
                    publicId = values[0] as String,
                    request = values[1] as RepaymentDraftConfirmRequestDto,
                    idempotencyKey = values[2] as String?,
                )
                confirmResult ?: draftDto(publicId = values[0] as String, status = RepaymentDraftStatuses.CONFIRMED)
            }
            "dismissRepaymentDraft" -> {
                dismissCalls += values[0] as String
                dismissResult ?: draftDto(publicId = values[0] as String, status = RepaymentDraftStatuses.DISMISSED)
            }
            else -> error("unexpected ApiService call: ${method.name}")
        }
    }

    private fun objectMethod(proxy: Any, method: Method, args: Array<out Any?>?): Any? = when (method.name) {
        "toString" -> "RepaymentDraftApiProxy"
        "hashCode" -> System.identityHashCode(proxy)
        "equals" -> proxy === args?.firstOrNull()
        else -> null
    }
}

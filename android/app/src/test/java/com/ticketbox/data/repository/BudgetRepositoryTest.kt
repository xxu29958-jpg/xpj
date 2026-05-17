package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.BudgetCategoryDto
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BudgetCategoryDraft
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.security.SessionTokenStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import java.lang.reflect.InvocationHandler
import java.lang.reflect.Proxy
import java.util.TimeZone
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class BudgetRepositoryTest {
    @Test
    fun monthlyBudgetForwardsMonthTimezoneAndMapsDomain() = withTimezone("Asia/Shanghai") {
        runTest {
            val api = BudgetApiHandler()
            val repository = repository(api)

            val result = repository.monthlyBudget(" 2026-05 ").getOrThrow()

            assertEquals("2026-05", api.monthlyBudgetCalls.single().month)
            assertEquals("Asia/Shanghai", api.monthlyBudgetCalls.single().timezone)
            assertEquals("owner", result.ledgerId)
            assertEquals("餐饮", result.categoryBudgets.single().category)
        }
    }

    @Test
    fun saveMonthlyBudgetForwardsNormalizedRequest() = withTimezone("UTC") {
        runTest {
            val api = BudgetApiHandler()
            val repository = repository(api)

            val result = repository.saveMonthlyBudget(
                " 2026-05 ",
                BudgetMonthlyUpdate(
                    totalAmountCents = 300000,
                    nonMonthlyAmountCents = 20000,
                    rolloverAmountCents = -10000,
                    excludedCategories = listOf("吃饭", "医疗", "餐饮"),
                    categoryBudgets = listOf(
                        BudgetCategoryDraft("吃饭", 120000),
                        BudgetCategoryDraft("餐饮", 130000),
                    ),
                ),
            ).getOrThrow()

            val call = api.updateBudgetCalls.single()
            assertEquals("2026-05", call.month)
            assertEquals("UTC", call.timezone)
            assertEquals(300000L, call.request.totalAmountCents)
            assertEquals(-10000L, call.request.rolloverAmountCents)
            assertEquals(listOf("餐饮", "医疗"), call.request.excludedCategories)
            assertEquals(1, call.request.categoryBudgets.size)
            assertEquals("餐饮", call.request.categoryBudgets.single().category)
            assertEquals(120000L, call.request.categoryBudgets.single().amountCents)
            assertTrue(result.configured)
        }
    }

    @Test
    fun viewerSaveShortCircuitsWithoutApiCall() = runTest {
        val api = BudgetApiHandler()
        val repository = repository(api, role = "viewer")

        val result = repository.saveMonthlyBudget(
            "2026-05",
            BudgetMonthlyUpdate(totalAmountCents = 300000),
        )

        assertTrue(result.isFailure)
        assertEquals("当前角色为只读，无法修改账本。", result.exceptionOrNull()?.message)
        assertTrue(api.updateBudgetCalls.isEmpty())
    }

    @Test
    fun backendPermissionDeniedMapsToReadOnlyMessage() = runTest {
        val api = BudgetApiHandler().apply {
            updateError = HttpException(
                Response.error<BudgetMonthlyDto>(
                    403,
                    """{"error":"permission_denied","message":"当前角色无权进行此操作。"}"""
                        .toResponseBody("application/json".toMediaType()),
                ),
            )
        }
        val repository = repository(api)

        val result = repository.saveMonthlyBudget(
            "2026-05",
            BudgetMonthlyUpdate(totalAmountCents = 300000),
        )

        assertTrue(result.isFailure)
        assertEquals("当前角色为只读，无法修改账本。", result.exceptionOrNull()?.message)
    }

    @Test
    fun invalidMonthIsRejectedBeforeApiCall() = runTest {
        val api = BudgetApiHandler()
        val repository = repository(api)

        val result = repository.monthlyBudget("2026-13")

        assertTrue(result.isFailure)
        assertEquals("预算月份不正确。", result.exceptionOrNull()?.message)
        assertTrue(api.monthlyBudgetCalls.isEmpty())
    }

    private fun repository(
        handler: BudgetApiHandler,
        role: String = "owner",
    ): BudgetRepository {
        val settings = BudgetFakeSettingsStore(role = role).apply {
            saveServerUrl("https://api.example.com")
        }
        val tokenStore = BudgetFakeTokenStore().apply { saveToken("session-token") }
        return BudgetRepository(
            apiClient = BudgetApiFactory(handler),
            settingsStore = settings,
            tokenStore = tokenStore,
        )
    }
}

private data class MonthlyBudgetCall(val month: String, val timezone: String?)

private data class UpdateBudgetCall(
    val month: String,
    val request: BudgetMonthlyUpdateRequestDto,
    val timezone: String?,
)

private class BudgetApiFactory(
    private val handler: BudgetApiHandler,
) : ApiServiceFactory {
    override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService {
        handler.baseUrls += baseUrl
        handler.tokens += tokenProvider()
        return handler.service()
    }
}

private class BudgetApiHandler : InvocationHandler {
    val baseUrls = mutableListOf<String>()
    val tokens = mutableListOf<String?>()
    val monthlyBudgetCalls = mutableListOf<MonthlyBudgetCall>()
    val updateBudgetCalls = mutableListOf<UpdateBudgetCall>()
    var updateError: Throwable? = null

    fun service(): ApiService {
        return Proxy.newProxyInstance(
            ApiService::class.java.classLoader,
            arrayOf(ApiService::class.java),
            this,
        ) as ApiService
    }

    override fun invoke(proxy: Any, method: java.lang.reflect.Method, args: Array<out Any?>?): Any? {
        if (method.declaringClass == Any::class.java) {
            return when (method.name) {
                "toString" -> "BudgetApiProxy"
                "hashCode" -> System.identityHashCode(proxy)
                "equals" -> proxy === args?.firstOrNull()
                else -> null
            }
        }
        val values = args.orEmpty()
        return when (method.name) {
            "monthlyBudget" -> {
                monthlyBudgetCalls += MonthlyBudgetCall(
                    month = values[0] as String,
                    timezone = values[1] as String?,
                )
                budgetDto()
            }
            "updateMonthlyBudget" -> {
                updateError?.let { throw it }
                updateBudgetCalls += UpdateBudgetCall(
                    month = values[0] as String,
                    request = values[1] as BudgetMonthlyUpdateRequestDto,
                    timezone = values[2] as String?,
                )
                budgetDto(configured = true)
            }
            else -> error("Unexpected API call: ${method.name}")
        }
    }
}

private fun budgetDto(configured: Boolean = true): BudgetMonthlyDto = BudgetMonthlyDto(
    ledgerId = "owner",
    month = "2026-05",
    configured = configured,
    totalAmountCents = 300000,
    rolloverAmountCents = 0,
    fixedAmountCents = 50000,
    nonMonthlyAmountCents = 20000,
    flexBudgetCents = 230000,
    spentAmountCents = 120000,
    excludedAmountCents = 0,
    remainingAmountCents = 180000,
    overspentAmountCents = 0,
    excludedCategories = emptyList(),
    excludedBreakdown = emptyList(),
    categoryBudgets = listOf(
        BudgetCategoryDto(
            category = "吃饭",
            amountCents = 120000,
            spentAmountCents = 80000,
            remainingAmountCents = 40000,
            overspentAmountCents = 0,
        ),
    ),
    updatedAt = "2026-05-13T00:00:00Z",
)

private class BudgetFakeSettingsStore(
    private var role: String? = "owner",
) : TicketboxSettingsStore {
    override val backgroundSettingsFlow: Flow<BackgroundSettings> = MutableStateFlow(BackgroundSettings())
    private var serverUrl: String? = null

    override fun serverUrl(): String? = serverUrl
    override fun appSkinKey(): String? = null
    override fun monthlyBudgetCents(): Long? = null
    override fun saveMonthlyBudgetCents(amountCents: Long?) = Unit
    override fun lastConfirmedSyncAt(): String? = null
    override fun accountName(): String? = "我"
    override fun ledgerName(): String? = "我的小票夹"
    override fun activeLedgerId(): String? = "owner"
    override fun activeLedgerName(): String? = "我的小票夹"
    override fun availableLedgersJson(): String? = null
    override fun observeActiveLedgerId(): Flow<String?> = MutableStateFlow("owner")
    override fun saveActiveLedger(ledgerId: String, ledgerName: String) = Unit
    override fun saveAvailableLedgersJson(json: String?) = Unit
    override fun deviceName(): String? = "Pixel"
    override fun role(): String? = role
    override fun boundAt(): String? = "2026-05-13T00:00:00Z"
    override fun saveIdentity(
        accountName: String,
        ledgerId: String,
        ledgerName: String,
        deviceName: String,
        role: String,
        boundAt: String,
    ) {
        this.role = role
    }
    override fun saveLastConfirmedSyncAt(value: String) = Unit
    override fun clearLastConfirmedSyncAt() = Unit
    override fun lastUploadAt(): String? = null
    override fun saveLastUploadAt(value: String) = Unit
    override fun saveAppSkinKey(skinKey: String) = Unit
    override fun currencyCodeKey(): String? = null
    override fun saveCurrencyCodeKey(currencyKey: String) = Unit
    override fun observeCurrencyCodeKey(): Flow<String?> = MutableStateFlow(null)
    override fun saveServerUrl(serverUrl: String) {
        this.serverUrl = serverUrl.trim().trimEnd('/')
    }
    override fun isBound(): Boolean = !serverUrl.isNullOrBlank()
    override fun markUnlocked() = Unit
    override fun markBackgrounded() = Unit
    override fun requiresUnlock(): Boolean = false
    override fun clear() {
        serverUrl = null
        role = null
    }
}

private class BudgetFakeTokenStore : SessionTokenStore {
    private var token: String? = null
    override fun saveToken(token: String) { this.token = token }
    override fun getToken(): String? = token
    override fun clear() { token = null }
}

private fun withTimezone(id: String, block: () -> Unit) {
    val old = TimeZone.getDefault()
    TimeZone.setDefault(TimeZone.getTimeZone(id))
    try {
        block()
    } finally {
        TimeZone.setDefault(old)
    }
}

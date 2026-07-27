package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.local.PersistedLedgerIdentity
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.BudgetAdviceDto
import com.ticketbox.data.remote.dto.BudgetAdviseRequestDto
import com.ticketbox.data.remote.dto.BudgetAdviseResponseDto
import com.ticketbox.data.remote.dto.BudgetCategoryDto
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import com.ticketbox.data.remote.dto.BudgetSuggestionDto
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BudgetCategoryDraft
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.security.LocalSessionIdentity
import com.ticketbox.security.SessionCredentialProvider
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.withTimeout
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import retrofit2.Response
import java.lang.reflect.InvocationHandler
import java.lang.reflect.Proxy
import java.util.TimeZone
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class BudgetRepositoryTest {
    @Test
    fun monthlyBudgetForwardsMonthTimezoneAndMapsDomain() = withTimezone("Asia/Shanghai") {
        runTest {
            val api = BudgetApiHandler()
            val (repository) = repository(api)

            val result = repository.monthlyBudget(" 2026-05 ").getOrThrow()

            assertEquals("2026-05", api.monthlyBudgetCalls.single().month)
            assertEquals("Asia/Shanghai", api.monthlyBudgetCalls.single().timezone)
            assertEquals("owner", result.ledgerId)
            assertEquals("餐饮", result.categoryBudgets.single().category)

            val advice = repository.requestBudgetAdvice(" 2026-05 ").getOrThrow()

            assertEquals("2026-05", api.adviceCalls.single().month)
            assertEquals("Asia/Shanghai", api.adviceCalls.single().timezone)
            assertEquals("mock", advice.providerName)
            assertEquals("餐饮", advice.advice?.suggestions?.single()?.category)
            assertEquals(80_000L, advice.advice?.suggestions?.single()?.suggestedAmountCents)
            assertEquals("advisor_ready", advice.reasonCode)
        }
    }

    @Test
    fun monthlyBudgetCanUseExplicitTimezone() = withTimezone("America/Los_Angeles") {
        runTest {
            val api = BudgetApiHandler()
            val (repository) = repository(api)

            val result = repository.monthlyBudget("2026-05", timezone = "Asia/Shanghai")
                .getOrThrow()

            assertEquals("2026-05", api.monthlyBudgetCalls.single().month)
            assertEquals("Asia/Shanghai", api.monthlyBudgetCalls.single().timezone)
            assertEquals("owner", result.ledgerId)
        }
    }

    @Test
    fun saveMonthlyBudgetForwardsNormalizedRequest() = withTimezone("UTC") {
        runTest {
            val api = BudgetApiHandler()
            val (repository, binding) = repository(api)

            val result = repository.saveMonthlyBudget(
                binding,
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
        val (repository, binding) = repository(api, role = "viewer")

        val result = repository.saveMonthlyBudget(
            binding,
            "2026-05",
            BudgetMonthlyUpdate(totalAmountCents = 300000),
        )

        assertTrue(result.isFailure)
        assertEquals("当前角色为只读，无法修改账本。", result.exceptionOrNull()?.message)
        assertTrue(api.updateBudgetCalls.isEmpty())

        val advice = repository.requestBudgetAdvice("2026-05")

        assertTrue(advice.isFailure)
        assertEquals(
            "permission_denied",
            (advice.exceptionOrNull() as? RepositoryException)?.errorCode,
        )
        assertTrue(api.adviceCalls.isEmpty())
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
        val (repository, binding) = repository(api)

        val result = repository.saveMonthlyBudget(
            binding,
            "2026-05",
            BudgetMonthlyUpdate(totalAmountCents = 300000),
        )

        assertTrue(result.isFailure)
        assertEquals("当前角色为只读，无法修改账本。", result.exceptionOrNull()?.message)
    }

    @Test
    fun backendAdvisorOwnerRequiredPropagatesErrorCode() = runTest {
        // 218-B4 review: the VM maps ai_advisor_owner_required /
        // ai_advisor_not_confirmed to a terminal no-retry state, which depends on
        // NetworkErrorHandler preserving the backend error code (and the
        // registered server copy) through RepositoryException.
        val api = BudgetApiHandler().apply {
            adviceError = HttpException(
                Response.error<BudgetAdviseResponseDto>(
                    403,
                    """{"error":"ai_advisor_owner_required","message":"只有账本拥有者可以调用外部 AI 预算建议。"}"""
                        .toResponseBody("application/json".toMediaType()),
                ),
            )
        }
        val (repository) = repository(api)

        val advice = repository.requestBudgetAdvice("2026-05")

        assertTrue(advice.isFailure)
        val exception = advice.exceptionOrNull() as? RepositoryException
        assertEquals("ai_advisor_owner_required", exception?.errorCode)
        assertEquals("只有账本拥有者可以调用外部 AI 预算建议。", exception?.message)
    }

    @Test
    fun concurrentAdviceCallsShareSingleApiInvocation() = runBlocking {
        // 218-B4 review P2: a live advice call is quota-counted server-side the
        // moment it starts, so concurrent callers must attach to one in-flight
        // call — one API hit, both callers observe the same result.
        val api = BudgetApiHandler().apply {
            adviceEntered = CountDownLatch(1)
            adviceRelease = CountDownLatch(1)
        }
        val (repository) = repository(api)

        val first = async(Dispatchers.IO) { repository.requestBudgetAdvice("2026-05") }
        assertTrue(api.adviceEntered?.await(5, TimeUnit.SECONDS) == true)
        val second = async(Dispatchers.IO) { repository.requestBudgetAdvice("2026-05") }
        delay(200)
        api.adviceRelease?.countDown()

        val firstResult = first.await()
        val secondResult = second.await()
        assertEquals(1, api.adviceCalls.size)
        assertTrue(firstResult.isSuccess)
        assertEquals(firstResult.getOrNull(), secondResult.getOrNull())
    }

    @Test
    fun adviceSuccessIsCachedAndServedFromCache() = runTest {
        val api = BudgetApiHandler()
        val (repository) = repository(api)

        val advice = repository.requestBudgetAdvice("2026-05").getOrThrow()

        assertEquals(advice, repository.cachedBudgetAdvice("2026-05"))
        assertEquals(advice, repository.cachedBudgetAdvice(" 2026-05 "))
        assertNull(repository.cachedBudgetAdvice("2026-06"))
    }

    @Test
    fun adviceFailureLeavesCacheAbsent() = runTest {
        val api = BudgetApiHandler().apply {
            adviceError = HttpException(
                Response.error<BudgetAdviseResponseDto>(
                    403,
                    """{"error":"ai_advisor_owner_required","message":"只有账本拥有者可以调用外部 AI 预算建议。"}"""
                        .toResponseBody("application/json".toMediaType()),
                ),
            )
        }
        val (repository) = repository(api)

        assertTrue(repository.requestBudgetAdvice("2026-05").isFailure)
        assertNull(repository.cachedBudgetAdvice("2026-05"))
    }

    @Test
    fun invalidMonthIsRejectedBeforeApiCall() = runTest {
        val api = BudgetApiHandler()
        val (repository) = repository(api)

        val result = repository.monthlyBudget("2026-13")

        assertTrue(result.isFailure)
        assertEquals("预算月份不正确。", result.exceptionOrNull()?.message)
        assertTrue(api.monthlyBudgetCalls.isEmpty())
    }

    private fun repository(
        handler: BudgetApiHandler,
        role: String = "owner",
    ): BudgetRepositoryFixture {
        val tokenStore = TestSessionFixture(
            identity = LocalSessionIdentity(
                accountName = "我",
                ledgerId = "owner",
                ledgerName = "我的小票夹",
                deviceName = "Pixel",
                role = role,
                boundAt = "2026-05-01T00:00:00Z",
            ),
        ).apply { saveToken("session-token") }
        val apiClient = BudgetApiFactory(handler)
        val provider = testApiServiceProvider(apiClient, tokenStore)
        return BudgetRepositoryFixture(
            repository = BudgetRepository(apiProvider = provider),
            binding = requireNotNull(LedgerRequestGuard(provider).captureLogicalBinding()),
        )
    }
}

/** 218-B4 review P1: the advice in-flight/cache state is keyed by the full
 *  logical session binding (server + account + ledger + generations), not the
 *  ledger id alone — ledger ids like "owner" repeat across households, so a
 *  ledgerId-only key would leak one household's advice into another after an
 *  unbind + re-pair. Separate class to stay under the per-class function cap. */
class BudgetRepositoryAdviceBindingTest {
    @Test
    fun changedAdviceInputStampInvalidatesCache() = runTest {
        val api = BudgetApiHandler()
        val tokenStore = TestSessionFixture().apply { saveToken("session-token") }
        val repository = repository(api, tokenStore)

        repository.requestBudgetAdvice("2026-05").getOrThrow()
        // First delivery of a source's stamp cannot prove the cache predates
        // the server state — it invalidates conservatively.
        repository.adviceCallStore.noteAdviceInputSnapshot(ADVICE_INPUT_CONFIRMED_EXPENSES, "n=10;rv=7;ua=t1")
        assertNull(repository.cachedBudgetAdvice("2026-05"))

        // Re-cache, then a CHANGED server snapshot (e.g. another family device
        // wrote, and a refresh delivered it) invalidates again — a reopen must
        // refetch rather than serve pre-change advice.
        repository.requestBudgetAdvice("2026-05").getOrThrow()
        repository.adviceCallStore.noteAdviceInputSnapshot(ADVICE_INPUT_CONFIRMED_EXPENSES, "n=11;rv=8;ua=t2")

        assertNull(repository.cachedBudgetAdvice("2026-05"))
        repository.requestBudgetAdvice("2026-05").getOrThrow()
        assertEquals(3, api.adviceCalls.size)
    }

    @Test
    fun identicalAdviceInputStampPreservesCache() = runTest {
        val api = BudgetApiHandler()
        val tokenStore = TestSessionFixture().apply { saveToken("session-token") }
        val repository = repository(api, tokenStore)

        val advice = repository.requestBudgetAdvice("2026-05").getOrThrow()
        repository.adviceCallStore.noteAdviceInputSnapshot(ADVICE_INPUT_CONFIRMED_EXPENSES, "n=10;rv=7;ua=t1")
        repository.requestBudgetAdvice("2026-05").getOrThrow()

        // A no-op refresh re-delivers the SAME stamp — the cache survives and
        // reopening spends no additional live-advisor call.
        repository.adviceCallStore.noteAdviceInputSnapshot(ADVICE_INPUT_CONFIRMED_EXPENSES, "n=10;rv=7;ua=t1")

        assertEquals(advice, repository.cachedBudgetAdvice("2026-05"))
        assertEquals(2, api.adviceCalls.size)
    }

    @Test
    fun adviceInputWriteInvalidatesCache() = runTest {
        val api = BudgetApiHandler()
        val tokenStore = TestSessionFixture().apply { saveToken("session-token") }
        val repository = repository(api, tokenStore)

        val advice = repository.requestBudgetAdvice("2026-05").getOrThrow()
        assertEquals(advice, repository.cachedBudgetAdvice("2026-05"))

        // The refresh points of the advice-input write paths (income plan /
        // recurring / budget / expense saves) call this — a reopen must then
        // recompute instead of restoring pre-write limits.
        repository.invalidateBudgetAdvice()

        assertNull(repository.cachedBudgetAdvice("2026-05"))
        repository.requestBudgetAdvice("2026-05").getOrThrow()
        assertEquals(2, api.adviceCalls.size)
    }

    @Test
    fun unrelatedRepositoryCallLeavesCacheIntact() = runTest {
        val api = BudgetApiHandler()
        val tokenStore = TestSessionFixture().apply { saveToken("session-token") }
        val repository = repository(api, tokenStore)

        val advice = repository.requestBudgetAdvice("2026-05").getOrThrow()

        // A plain read is not an advice-input write — the cache survives.
        repository.monthlyBudget("2026-05").getOrThrow()
        assertEquals(advice, repository.cachedBudgetAdvice("2026-05"))
    }

    @Test
    fun nullAdviceSuccessIsNotCached() = runTest {
        // provider_empty returns HTTP 200 with advice == null — a terminal
        // state that must never be restored, or a later operator-side fix
        // would stay invisible behind the cached state.
        val api = BudgetApiHandler().apply {
            adviceResponse = BudgetAdviseResponseDto(
                advice = null,
                providerName = "empty",
                reasonCode = "ai_advisor_provider_empty",
            )
        }
        val tokenStore = TestSessionFixture().apply { saveToken("session-token") }
        val repository = repository(api, tokenStore)

        val result = repository.requestBudgetAdvice("2026-05").getOrThrow()

        assertNull(result.advice)
        assertNull(repository.cachedBudgetAdvice("2026-05"))
    }

    @Test
    fun adviceCacheIsScopedToRequestTimezone() {
        // The request timezone is the device ZoneId (TimeZone.getDefault().id
        // via currentTimezoneId()); the same textual month under a different
        // timezone is a different key — no stale restore, no wrong dedupe.
        withTimezone("Asia/Shanghai") {
            runBlocking {
                val api = BudgetApiHandler()
                val tokenStore = TestSessionFixture().apply { saveToken("session-token") }
                val repository = repository(api, tokenStore)

                val shanghaiAdvice = repository.requestBudgetAdvice("2026-05").getOrThrow()
                assertEquals(shanghaiAdvice, repository.cachedBudgetAdvice("2026-05"))
                assertEquals("Asia/Shanghai", api.adviceCalls.single().timezone)

                withTimezone("America/Los_Angeles") {
                    runBlocking {
                        assertNull(repository.cachedBudgetAdvice("2026-05"))
                        repository.requestBudgetAdvice("2026-05").getOrThrow()
                        assertEquals(2, api.adviceCalls.size)
                        assertEquals("America/Los_Angeles", api.adviceCalls[1].timezone)
                    }
                }

                // Both entries coexist: back in the original timezone the first
                // result is served again with no third call.
                assertEquals(shanghaiAdvice, repository.cachedBudgetAdvice("2026-05"))
                assertEquals(2, api.adviceCalls.size)
            }
        }
    }

    @Test
    fun preWriteInFlightCallDoesNotRepopulateCacheAfterInvalidation() = runBlocking {
        val api = BudgetApiHandler().apply {
            adviceResponses += BudgetAdviseResponseDto(
                advice = BudgetAdviceDto(
                    summary = "旧建议",
                    suggestions = emptyList(),
                    confidence = 0.5,
                ),
                providerName = "mock",
                reasonCode = "advisor_ready",
            )
            adviceResponses += BudgetAdviseResponseDto(
                advice = BudgetAdviceDto(
                    summary = "新建议",
                    suggestions = emptyList(),
                    confidence = 0.6,
                ),
                providerName = "mock",
                reasonCode = "advisor_ready",
            )
            adviceEntered = CountDownLatch(2)
            adviceRelease = CountDownLatch(1)
        }
        val tokenStore = TestSessionFixture().apply { saveToken("session-token") }
        val repository = repository(api, tokenStore)

        val first = async(Dispatchers.IO) { repository.requestBudgetAdvice("2026-05") }
        withTimeout(5_000) {
            while (api.adviceEntered?.count != 1L) delay(10)
        }

        // An advice-input write lands mid-flight: invalidation bumps the data
        // generation, so the post-write request must NOT attach to the
        // pre-write call.
        repository.invalidateBudgetAdvice()
        val second = async(Dispatchers.IO) { repository.requestBudgetAdvice("2026-05") }
        assertTrue(api.adviceEntered?.await(5, TimeUnit.SECONDS) == true)
        api.adviceRelease?.countDown()

        val staleResult = first.await().getOrThrow()
        val freshResult = second.await().getOrThrow()
        assertEquals(2, api.adviceCalls.size)
        // The pre-write success is still delivered to its own caller (allowed),
        // but only the post-write result repopulates the cache.
        assertEquals("旧建议", staleResult.advice?.summary)
        assertEquals("新建议", freshResult.advice?.summary)
        assertEquals("新建议", repository.cachedBudgetAdvice("2026-05")?.advice?.summary)
    }

    @Test
    fun adviceCacheIsScopedToLogicalBinding() = runTest {
        val api = BudgetApiHandler()
        val tokenStore = TestSessionFixture().apply { saveToken("session-token") }
        val repository = repository(api, tokenStore)

        val advice = repository.requestBudgetAdvice("2026-05").getOrThrow()
        assertEquals(advice, repository.cachedBudgetAdvice("2026-05"))

        // Unbind + re-pair to a DIFFERENT household whose ledger id is also
        // "owner": the previous binding's entry must be unreachable.
        val current = requireNotNull(tokenStore.sessionStore.currentSession())
        tokenStore.sessionStore.replaceForFixture(
            current.copy(
                sessionGeneration = "other-household-session",
                bindingRevision = "other-household-binding",
                serverUrl = "https://other.example.com",
            ),
        )

        assertNull(repository.cachedBudgetAdvice("2026-05"))
        repository.requestBudgetAdvice("2026-05").getOrThrow()
        assertEquals(2, api.adviceCalls.size)
    }

    @Test
    fun inFlightAdviceIsScopedToLogicalBinding() = runBlocking {
        val api = BudgetApiHandler().apply {
            adviceEntered = CountDownLatch(2)
            adviceRelease = CountDownLatch(1)
        }
        val tokenStore = TestSessionFixture().apply { saveToken("session-token") }
        val repository = repository(api, tokenStore)

        val first = async(Dispatchers.IO) { repository.requestBudgetAdvice("2026-05") }
        // Wait until the first call is bound and inside the API, then re-pair:
        // the new binding must NOT attach to the stale binding's deferred.
        withTimeout(5_000) {
            while (api.adviceEntered?.count != 1L) delay(10)
        }
        val current = requireNotNull(tokenStore.sessionStore.currentSession())
        tokenStore.sessionStore.replaceForFixture(
            current.copy(
                sessionGeneration = "other-household-session",
                bindingRevision = "other-household-binding",
                serverUrl = "https://other.example.com",
            ),
        )
        val second = async(Dispatchers.IO) { repository.requestBudgetAdvice("2026-05") }
        assertTrue(api.adviceEntered?.await(5, TimeUnit.SECONDS) == true)
        api.adviceRelease?.countDown()

        val firstResult = first.await()
        val secondResult = second.await()
        assertEquals(2, api.adviceCalls.size)
        // The stale-binding call completes as ledger-changed (post-call re-check)
        // and never writes the cache; the new binding's call succeeds and does.
        assertTrue(firstResult.isFailure)
        assertTrue(secondResult.isSuccess)
        assertEquals(secondResult.getOrNull(), repository.cachedBudgetAdvice("2026-05"))
    }

    private fun repository(
        handler: BudgetApiHandler,
        tokenStore: TestSessionFixture,
    ): BudgetRepository = BudgetRepository(
        apiProvider = testApiServiceProvider(BudgetApiFactory(handler), tokenStore),
    )
}

private data class BudgetRepositoryFixture(
    val repository: BudgetRepository,
    val binding: LogicalSessionBinding,
)

private data class MonthlyBudgetCall(val month: String, val timezone: String?)

private data class AdviceCall(val month: String, val timezone: String?)

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
    val adviceCalls = mutableListOf<AdviceCall>()
    var updateError: Throwable? = null
    var adviceError: Throwable? = null
    var adviceEntered: CountDownLatch? = null
    var adviceRelease: CountDownLatch? = null
    var adviceResponse: BudgetAdviseResponseDto? = null
    val adviceResponses = mutableListOf<BudgetAdviseResponseDto>()

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
            "budgetAdvise" -> {
                adviceError?.let { throw it }
                adviceEntered?.countDown()
                adviceRelease?.await(10, TimeUnit.SECONDS)
                val request = values[0] as BudgetAdviseRequestDto
                val queuedResponse = synchronized(adviceResponses) {
                    adviceCalls += AdviceCall(
                        month = request.month,
                        timezone = request.timezone,
                    )
                    adviceResponses.removeFirstOrNull()
                }
                queuedResponse ?: adviceResponse ?: BudgetAdviseResponseDto(
                    advice = BudgetAdviceDto(
                        summary = "为弹性支出留出余量。",
                        suggestions = listOf(
                            BudgetSuggestionDto(
                                category = "餐饮",
                                suggestedAmountCents = 80_000,
                                rationale = "近期支出稳定。",
                            ),
                        ),
                        confidence = 0.8,
                    ),
                    providerName = "mock",
                    reasonCode = "advisor_ready",
                )
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

private fun withTimezone(id: String, block: () -> Unit) {
    val old = TimeZone.getDefault()
    TimeZone.setDefault(TimeZone.getTimeZone(id))
    try {
        block()
    } finally {
        TimeZone.setDefault(old)
    }
}

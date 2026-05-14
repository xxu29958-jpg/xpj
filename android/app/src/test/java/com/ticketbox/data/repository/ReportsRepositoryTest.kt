package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.DashboardCardDto
import com.ticketbox.data.remote.dto.DashboardCardsResponseDto
import com.ticketbox.data.remote.dto.DashboardCardsUpdateRequestDto
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.data.remote.dto.ReportCategoryComparisonDto
import com.ticketbox.data.remote.dto.ReportMerchantRankingDto
import com.ticketbox.data.remote.dto.ReportTrendPointDto
import com.ticketbox.data.remote.dto.ReportsOverviewDto
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.DashboardCardUpdate
import com.ticketbox.domain.model.DashboardSurface
import com.ticketbox.domain.model.GoalDraft
import com.ticketbox.domain.model.GoalProgressState
import com.ticketbox.domain.model.GoalUpdate
import com.ticketbox.domain.model.ReportGranularity
import com.ticketbox.domain.model.ReportRankingMetric
import com.ticketbox.domain.model.ReportsOverviewQuery
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
import kotlin.test.assertTrue

class ReportsRepositoryTest {
    @Test
    fun reportsOverviewForwardsNormalizedQueryAndMapsDomain() = withReportsTimezone("Asia/Shanghai") {
        runTest {
            val api = ReportsApiHandler()
            val repository = repository(api)

            val result = repository.reportsOverview(
                ReportsOverviewQuery(
                    month = " 2026-05 ",
                    granularity = ReportGranularity.Week,
                    topN = 50,
                    merchantCategory = "吃饭",
                    rankingMetric = ReportRankingMetric.Count,
                ),
            ).getOrThrow()

            val call = api.reportCalls.single()
            assertEquals("2026-05", call.month)
            assertEquals("week", call.granularity)
            assertEquals(20, call.topN)
            assertEquals("餐饮", call.merchantCategory)
            assertEquals("count", call.rankingMetric)
            assertEquals("Asia/Shanghai", call.timezone)
            assertEquals(ReportGranularity.Week, result.granularity)
            assertEquals("餐饮", result.merchantCategory)
            assertEquals("餐饮", result.categoryComparison.single().category)
        }
    }

    @Test
    fun goalsAndDashboardCardsUseTimezoneAndDomainTypes() = withReportsTimezone("UTC") {
        runTest {
            val api = ReportsApiHandler()
            val repository = repository(api)

            val goals = repository.goals(month = " 2026-05 ", includeArchived = true).getOrThrow()
            val created = repository.createGoal(
                GoalDraft(
                    name = " 本月餐饮 ",
                    month = " 2026-05 ",
                    targetAmountCents = 80000,
                    category = "吃饭",
                ),
            ).getOrThrow()
            val updated = repository.updateGoal(
                publicId = " goal-1 ",
                update = GoalUpdate(targetAmountCents = 90000, category = "购物"),
            ).getOrThrow()
            val cards = repository.dashboardCards(DashboardSurface.Android).getOrThrow()
            val savedCards = repository.updateDashboardCards(
                updates = listOf(
                    DashboardCardUpdate(" goals ", visible = true, position = 0),
                    DashboardCardUpdate("reports", visible = false, position = 1),
                ),
                surface = DashboardSurface.Android,
            ).getOrThrow()

            assertEquals("2026-05", api.goalsCalls.single().month)
            assertEquals(true, api.goalsCalls.single().includeArchived)
            assertEquals("UTC", api.goalsCalls.single().timezone)
            assertEquals(GoalProgressState.NearLimit, goals.single().progressState)
            assertEquals("餐饮", created.category)
            assertEquals("购物", updated.category)
            assertEquals("本月餐饮", api.createGoalCalls.single().request.name)
            assertEquals("餐饮", api.createGoalCalls.single().request.category)
            assertEquals("goal-1", api.updateGoalCalls.single().publicId)
            assertEquals("android", api.dashboardCardCalls.single())
            assertEquals("goals", api.updateDashboardCardCalls.single().request.cards.first().key)
            assertEquals("reports", savedCards.items[1].key)
            assertEquals(DashboardSurface.Android, cards.surface)
        }
    }

    @Test
    fun viewerWritesShortCircuitWithoutApiCall() = runTest {
        val api = ReportsApiHandler()
        val repository = repository(api, role = "viewer")

        val goalResult = repository.createGoal(
            GoalDraft(
                name = "本月餐饮",
                month = "2026-05",
                targetAmountCents = 80000,
            ),
        )
        val cardsResult = repository.updateDashboardCards(
            updates = listOf(DashboardCardUpdate("goals", visible = true, position = 0)),
        )

        assertTrue(goalResult.isFailure)
        assertTrue(cardsResult.isFailure)
        assertEquals("当前角色为只读，无法修改账本。", goalResult.exceptionOrNull()?.message)
        assertEquals("当前角色为只读，无法修改账本。", cardsResult.exceptionOrNull()?.message)
        assertTrue(api.createGoalCalls.isEmpty())
        assertTrue(api.updateDashboardCardCalls.isEmpty())
    }

    @Test
    fun emptyDashboardUpdateResetsServerPreferences() = runTest {
        val api = ReportsApiHandler()
        val repository = repository(api)

        val result = repository.updateDashboardCards(emptyList(), DashboardSurface.Android)

        assertTrue(result.isSuccess)
        assertTrue(api.updateDashboardCardCalls.single().request.cards.isEmpty())
        assertEquals("android", api.updateDashboardCardCalls.single().surface)
    }

    @Test
    fun backendPermissionDeniedMapsToReadOnlyMessage() = runTest {
        val api = ReportsApiHandler().apply {
            createGoalError = HttpException(
                Response.error<GoalDto>(
                    403,
                    """{"error":"permission_denied","message":"当前角色无权进行此操作。"}"""
                        .toResponseBody("application/json".toMediaType()),
                ),
            )
        }
        val repository = repository(api)

        val result = repository.createGoal(
            GoalDraft(
                name = "本月餐饮",
                month = "2026-05",
                targetAmountCents = 80000,
            ),
        )

        assertTrue(result.isFailure)
        assertEquals("当前角色为只读，无法修改账本。", result.exceptionOrNull()?.message)
    }

    @Test
    fun invalidDashboardUpdateIsRejectedBeforeApiCall() = runTest {
        val api = ReportsApiHandler()
        val repository = repository(api)

        val result = repository.updateDashboardCards(
            updates = listOf(
                DashboardCardUpdate("goals", visible = true, position = 0),
                DashboardCardUpdate(" goals ", visible = false, position = 1),
            ),
        )

        assertTrue(result.isFailure)
        assertEquals("卡片不能重复。", result.exceptionOrNull()?.message)
        assertTrue(api.updateDashboardCardCalls.isEmpty())
    }

    private fun repository(
        handler: ReportsApiHandler,
        role: String = "owner",
    ): ReportsRepository {
        val settings = ReportsFakeSettingsStore(role = role).apply {
            saveServerUrl("https://api.zen70.cn")
        }
        val tokenStore = ReportsFakeTokenStore().apply { saveToken("session-token") }
        return ReportsRepository(
            apiClient = ReportsApiFactory(handler),
            settingsStore = settings,
            tokenStore = tokenStore,
        )
    }
}

private data class ReportsOverviewCall(
    val month: String?,
    val granularity: String,
    val topN: Int,
    val merchantCategory: String?,
    val rankingMetric: String,
    val timezone: String?,
)

private data class GoalsCall(
    val month: String?,
    val includeArchived: Boolean,
    val timezone: String?,
)

private data class CreateGoalCall(
    val request: GoalCreateRequestDto,
    val timezone: String?,
)

private data class UpdateGoalCall(
    val publicId: String,
    val request: GoalUpdateRequestDto,
    val timezone: String?,
)

private data class UpdateDashboardCardsCall(
    val request: DashboardCardsUpdateRequestDto,
    val surface: String,
)

private class ReportsApiFactory(
    private val handler: ReportsApiHandler,
) : ApiServiceFactory {
    override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService {
        handler.baseUrls += baseUrl
        handler.tokens += tokenProvider()
        return handler.service()
    }
}

private class ReportsApiHandler : InvocationHandler {
    val baseUrls = mutableListOf<String>()
    val tokens = mutableListOf<String?>()
    val reportCalls = mutableListOf<ReportsOverviewCall>()
    val goalsCalls = mutableListOf<GoalsCall>()
    val createGoalCalls = mutableListOf<CreateGoalCall>()
    val updateGoalCalls = mutableListOf<UpdateGoalCall>()
    val archiveGoalCalls = mutableListOf<Pair<String, String?>>()
    val dashboardCardCalls = mutableListOf<String>()
    val updateDashboardCardCalls = mutableListOf<UpdateDashboardCardsCall>()
    var createGoalError: Throwable? = null

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
                "toString" -> "ReportsApiProxy"
                "hashCode" -> System.identityHashCode(proxy)
                "equals" -> proxy === args?.firstOrNull()
                else -> null
            }
        }
        val values = args.orEmpty()
        return when (method.name) {
            "reportsOverview" -> {
                reportCalls += ReportsOverviewCall(
                    month = values[0] as String?,
                    granularity = values[1] as String,
                    topN = values[2] as Int,
                    merchantCategory = values[3] as String?,
                    rankingMetric = values[4] as String,
                    timezone = values[5] as String?,
                )
                reportsDto(granularity = values[1] as String, rankingMetric = values[4] as String)
            }
            "reportsOverviewCsv" -> Response.success("csv".toResponseBody("text/csv".toMediaType()))
            "goals" -> {
                goalsCalls += GoalsCall(
                    month = values[0] as String?,
                    includeArchived = values[1] as Boolean,
                    timezone = values[2] as String?,
                )
                GoalListResponseDto(items = listOf(goalDto()))
            }
            "createGoal" -> {
                createGoalError?.let { throw it }
                createGoalCalls += CreateGoalCall(
                    request = values[0] as GoalCreateRequestDto,
                    timezone = values[1] as String?,
                )
                goalDto(category = (values[0] as GoalCreateRequestDto).category)
            }
            "goal" -> goalDto()
            "updateGoal" -> {
                updateGoalCalls += UpdateGoalCall(
                    publicId = values[0] as String,
                    request = values[1] as GoalUpdateRequestDto,
                    timezone = values[2] as String?,
                )
                goalDto(category = (values[1] as GoalUpdateRequestDto).category)
            }
            "archiveGoal" -> {
                archiveGoalCalls += (values[0] as String) to (values[1] as String?)
                goalDto(status = "archived", progressState = "archived", archivedAt = "2026-05-14T00:00:00Z")
            }
            "dashboardCards" -> {
                dashboardCardCalls += values[0] as String
                dashboardCardsDto(surface = values[0] as String)
            }
            "updateDashboardCards" -> {
                updateDashboardCardCalls += UpdateDashboardCardsCall(
                    request = values[0] as DashboardCardsUpdateRequestDto,
                    surface = values[1] as String,
                )
                dashboardCardsDto(surface = values[1] as String)
            }
            else -> error("Unexpected API call: ${method.name}")
        }
    }
}

private fun reportsDto(
    granularity: String = "day",
    rankingMetric: String = "amount",
): ReportsOverviewDto = ReportsOverviewDto(
    month = "2026-05",
    timezone = "Asia/Shanghai",
    granularity = granularity,
    totalAmountCents = 4200,
    count = 3,
    previousMonth = "2026-04",
    previousTotalAmountCents = 500,
    previousCount = 1,
    merchantCategory = "吃饭",
    rankingMetric = rankingMetric,
    trend = listOf(ReportTrendPointDto("2026-05-01", "05-01", 1200, 1)),
    merchantRanking = listOf(ReportMerchantRankingDto("星巴克", 2000, 2)),
    categoryComparison = listOf(
        ReportCategoryComparisonDto(
            category = "吃饭",
            amountCents = 2000,
            count = 2,
            previousAmountCents = 500,
            previousCount = 1,
            deltaAmountCents = 1500,
            deltaCount = 1,
        ),
    ),
)

private fun goalDto(
    category: String? = "餐饮",
    status: String = "active",
    progressState: String = "near_limit",
    archivedAt: String? = null,
): GoalDto = GoalDto(
    publicId = "goal-1",
    ledgerId = "owner",
    name = "本月餐饮",
    goalType = "spending_limit",
    period = "monthly",
    month = "2026-05",
    category = category,
    targetAmountCents = 80000,
    spentAmountCents = 64000,
    remainingAmountCents = 16000,
    progressPercent = 80,
    progressState = progressState,
    status = status,
    createdAt = "2026-05-13T00:00:00Z",
    updatedAt = "2026-05-13T00:00:00Z",
    archivedAt = archivedAt,
)

private fun dashboardCardsDto(surface: String = "android"): DashboardCardsResponseDto = DashboardCardsResponseDto(
    surface = surface,
    items = listOf(
        DashboardCardDto("goals", "目标", visible = true, position = 0),
        DashboardCardDto("reports", "报表", visible = false, position = 1),
    ),
)

private class ReportsFakeSettingsStore(
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

private class ReportsFakeTokenStore : SessionTokenStore {
    private var token: String? = null
    override fun saveToken(token: String) { this.token = token }
    override fun getToken(): String? = token
    override fun clear() { token = null }
}

private fun withReportsTimezone(id: String, block: () -> Unit) {
    val old = TimeZone.getDefault()
    TimeZone.setDefault(TimeZone.getTimeZone(id))
    try {
        block()
    } finally {
        TimeZone.setDefault(old)
    }
}

package com.ticketbox.data.repository

import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.DashboardCardDto
import com.ticketbox.data.remote.dto.DashboardCardsResponseDto
import com.ticketbox.data.remote.dto.DashboardCardsUpdateRequestDto
import com.ticketbox.data.remote.dto.DebtGoalLinkViewDto
import com.ticketbox.data.remote.dto.DebtRepaymentEvaluationDto
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
import kotlin.test.assertNull
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
                update = GoalUpdate(
                    expectedRowVersion = 1L,
                    targetAmountCents = 90000,
                    category = "购物",
                ),
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
    fun createDebtGoalSendsDebtShapeRequestAndMapsDomain() = withReportsTimezone("UTC") {
        runTest {
            val api = ReportsApiHandler()
            val repository = repository(api)

            val created = repository.createDebtGoal(
                name = " 还清欠款 ",
                debtPublicIds = listOf(" debt-a ", "", "debt-b", "debt-a"),
            ).getOrThrow()

            val call = api.createGoalCalls.single()
            assertEquals("还清欠款", call.request.name)
            assertEquals("debt_repayment", call.request.goalType)
            // trimmed + blanks dropped + de-duped, order preserved.
            assertEquals(listOf("debt-a", "debt-b"), call.request.debtPublicIds)
            // debt-goal shape: the spend fields are omitted (null on the wire).
            assertNull(call.request.month)
            assertNull(call.request.targetAmountCents)
            assertNull(call.request.category)
            assertEquals("UTC", call.timezone)
            assertTrue(created.isDebtRepayment)
        }
    }

    @Test
    fun createDebtGoalRejectedForViewerWithoutApiCall() = runTest {
        val api = ReportsApiHandler()
        val repository = repository(api, role = "viewer")

        val result = repository.createDebtGoal("还清欠款", listOf("debt-a"))

        assertTrue(result.isFailure)
        assertEquals("当前角色为只读，无法修改账本。", result.exceptionOrNull()?.message)
        assertTrue(api.createGoalCalls.isEmpty())
    }

    @Test
    fun createDebtGoalRejectsEmptyIdsBeforeApiCall() = runTest {
        val api = ReportsApiHandler()
        val repository = repository(api)

        val result = repository.createDebtGoal("还清欠款", listOf("  ", ""))

        assertTrue(result.isFailure)
        assertEquals("请至少关联一笔欠款。", result.exceptionOrNull()?.message)
        assertTrue(api.createGoalCalls.isEmpty())
    }

    @Test
    fun createDebtGoalRejectsBlankNameBeforeApiCall() = runTest {
        val api = ReportsApiHandler()
        val repository = repository(api)

        val result = repository.createDebtGoal("   ", listOf("debt-a"))

        assertTrue(result.isFailure)
        assertEquals("请输入目标名称。", result.exceptionOrNull()?.message)
        assertTrue(api.createGoalCalls.isEmpty())
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

    @Test
    fun debtGoalsListWithDebtTypeAndMapEvaluationBlock() = withReportsTimezone("UTC") {
        runTest {
            val api = ReportsApiHandler()
            val repository = repository(api)

            val goals = repository.debtGoals(includeArchived = true).getOrThrow()

            assertEquals("debt_repayment", api.goalsCalls.single().goalType)
            assertEquals(true, api.goalsCalls.single().includeArchived)
            assertEquals("UTC", api.goalsCalls.single().timezone)
            val goal = goals.single()
            assertTrue(goal.isDebtRepayment)
            val evaluation = goal.debtRepayment
            assertEquals("in_progress", evaluation?.evaluationState)
            assertEquals(2, evaluation?.linkedDebts?.size)
            assertEquals(listOf("debt-b"), evaluation?.voidedDebtPublicIds)
            assertEquals("i_owe", evaluation?.linkedDebts?.first()?.direction)
            assertEquals(listOf("debt-a"), evaluation?.nonVoidedDebtPublicIds)
        }
    }

    @Test
    fun replaceDebtLinksPassesOccTokenIdempotencyKeyAndCleanIds() = withReportsTimezone("UTC") {
        runTest {
            val api = ReportsApiHandler()
            val repository = repository(api)

            val updated = repository.replaceDebtLinks(
                publicId = " debt-goal-1 ",
                expectedRowVersion = 3L,
                debtPublicIds = listOf(" debt-a ", "", "debt-c"),
            ).getOrThrow()

            val call = api.replaceDebtLinksCalls.single()
            assertEquals("debt-goal-1", call.publicId)
            assertEquals(3L, call.request.expectedRowVersion)
            // blanks trimmed/dropped before the request leaves the repository.
            assertEquals(listOf("debt-a", "debt-c"), call.request.debtPublicIds)
            assertTrue(!call.idempotencyKey.isNullOrBlank())
            assertEquals("UTC", call.timezone)
            assertTrue(updated.isDebtRepayment)
        }
    }

    @Test
    fun acknowledgeIntegrityReviewPassesOccTokenAndIdempotencyKey() = runTest {
        val api = ReportsApiHandler()
        val repository = repository(api)

        val updated = repository.acknowledgeDebtIntegrityReview(
            publicId = " debt-goal-1 ",
            expectedRowVersion = 4L,
        ).getOrThrow()

        val call = api.acknowledgeIntegrityCalls.single()
        assertEquals("debt-goal-1", call.publicId)
        assertEquals(4L, call.request.expectedRowVersion)
        assertTrue(!call.idempotencyKey.isNullOrBlank())
        assertEquals(false, updated.debtRepayment?.needsReview)
    }

    @Test
    fun viewerDebtMutationsShortCircuitWithoutApiCall() = runTest {
        val api = ReportsApiHandler()
        val repository = repository(api, role = "viewer")

        val replaceResult = repository.replaceDebtLinks("debt-goal-1", 1L, listOf("debt-a"))
        val ackResult = repository.acknowledgeDebtIntegrityReview("debt-goal-1", 1L)

        assertTrue(replaceResult.isFailure)
        assertTrue(ackResult.isFailure)
        assertEquals("当前角色为只读，无法修改账本。", replaceResult.exceptionOrNull()?.message)
        assertEquals("当前角色为只读，无法修改账本。", ackResult.exceptionOrNull()?.message)
        assertTrue(api.replaceDebtLinksCalls.isEmpty())
        assertTrue(api.acknowledgeIntegrityCalls.isEmpty())
    }

    @Test
    fun replaceDebtLinksRejectsEmptyIdSetBeforeApiCall() = runTest {
        val api = ReportsApiHandler()
        val repository = repository(api)

        val result = repository.replaceDebtLinks("debt-goal-1", 1L, listOf("   ", ""))

        assertTrue(result.isFailure)
        assertEquals("请至少关联一笔欠款。", result.exceptionOrNull()?.message)
        assertTrue(api.replaceDebtLinksCalls.isEmpty())
    }

    @Test
    fun debtLinkStateConflictSurfacesAsFailure() = runTest {
        val api = ReportsApiHandler().apply {
            replaceDebtLinksError = HttpException(
                Response.error<GoalDto>(
                    409,
                    """{"error":"state_conflict","message":"目标已被其他设备修改。"}"""
                        .toResponseBody("application/json".toMediaType()),
                ),
            )
        }
        val repository = repository(api)

        val result = repository.replaceDebtLinks("debt-goal-1", 1L, listOf("debt-a"))

        assertTrue(result.isFailure)
    }

    private fun repository(
        handler: ReportsApiHandler,
        role: String = "owner",
    ): ReportsRepository {
        val settings = ReportsFakeSettingsStore(role = role).apply {
            saveServerUrl("https://api.example.com")
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
    val goalType: String?,
    val timezone: String?,
)

private data class ReplaceDebtLinksCall(
    val publicId: String,
    val request: com.ticketbox.data.remote.dto.DebtGoalLinksReplaceRequestDto,
    val idempotencyKey: String?,
    val timezone: String?,
)

private data class AcknowledgeIntegrityCall(
    val publicId: String,
    val request: com.ticketbox.data.remote.dto.DebtGoalIntegrityReviewRequestDto,
    val idempotencyKey: String?,
    val timezone: String?,
)

private data class CreateGoalCall(
    val request: GoalCreateRequestDto,
    val timezone: String?,
)

private data class UpdateGoalCall(
    val publicId: String,
    val request: GoalUpdateRequestDto,
    val idempotencyKey: String?,
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
    val replaceDebtLinksCalls = mutableListOf<ReplaceDebtLinksCall>()
    val acknowledgeIntegrityCalls = mutableListOf<AcknowledgeIntegrityCall>()
    val dashboardCardCalls = mutableListOf<String>()
    val updateDashboardCardCalls = mutableListOf<UpdateDashboardCardsCall>()
    var createGoalError: Throwable? = null
    var debtGoalsResult: GoalListResponseDto? = null
    var replaceDebtLinksError: Throwable? = null
    var acknowledgeIntegrityError: Throwable? = null

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
                // ADR-0049 §6 (slice 7): arg order is now
                // [month, includeArchived, goalType, timezone].
                val goalType = values[2] as String?
                goalsCalls += GoalsCall(
                    month = values[0] as String?,
                    includeArchived = values[1] as Boolean,
                    goalType = goalType,
                    timezone = values[3] as String?,
                )
                if (goalType == "debt_repayment") {
                    debtGoalsResult ?: GoalListResponseDto(items = listOf(debtGoalDto()))
                } else {
                    GoalListResponseDto(items = listOf(goalDto()))
                }
            }
            "replaceGoalDebtLinks" -> {
                replaceDebtLinksError?.let { throw it }
                replaceDebtLinksCalls += ReplaceDebtLinksCall(
                    publicId = values[0] as String,
                    request = values[1] as com.ticketbox.data.remote.dto.DebtGoalLinksReplaceRequestDto,
                    idempotencyKey = values[2] as String?,
                    timezone = values[3] as String?,
                )
                debtGoalDto()
            }
            "acknowledgeGoalIntegrityReview" -> {
                acknowledgeIntegrityError?.let { throw it }
                acknowledgeIntegrityCalls += AcknowledgeIntegrityCall(
                    publicId = values[0] as String,
                    request = values[1] as com.ticketbox.data.remote.dto.DebtGoalIntegrityReviewRequestDto,
                    idempotencyKey = values[2] as String?,
                    timezone = values[3] as String?,
                )
                debtGoalDto(needsReview = false)
            }
            "createGoal" -> {
                createGoalError?.let { throw it }
                val request = values[0] as GoalCreateRequestDto
                createGoalCalls += CreateGoalCall(
                    request = request,
                    timezone = values[1] as String?,
                )
                // ADR-0049 §6 (slice 8b): a debt_repayment create returns a debt goal shape.
                if (request.goalType == "debt_repayment") debtGoalDto() else goalDto(category = request.category)
            }
            "goal" -> goalDto()
            "updateGoal" -> {
                // ADR-0042 Slice F: arg order is now
                // [publicId, request, idempotencyKey, timezone].
                updateGoalCalls += UpdateGoalCall(
                    publicId = values[0] as String,
                    request = values[1] as GoalUpdateRequestDto,
                    idempotencyKey = values[2] as String?,
                    timezone = values[3] as String?,
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
    rowVersion = 1L,
    archivedAt = archivedAt,
)

private fun debtGoalDto(
    publicId: String = "debt-goal-1",
    evaluationState: String = "in_progress",
    needsReview: Boolean = false,
    rowVersion: Long = 3L,
): GoalDto = GoalDto(
    publicId = publicId,
    ledgerId = "owner",
    name = "还清欠款",
    goalType = "debt_repayment",
    period = "monthly",
    // ADR-0049 §6: the spending-shape fields are null for a debt goal.
    month = null,
    category = null,
    targetAmountCents = null,
    spentAmountCents = null,
    remainingAmountCents = null,
    progressPercent = null,
    progressState = evaluationState,
    status = "active",
    createdAt = "2026-06-13T00:00:00Z",
    updatedAt = "2026-06-15T00:00:00Z",
    rowVersion = rowVersion,
    archivedAt = null,
    debtRepayment = DebtRepaymentEvaluationDto(
        goalVersion = 2,
        evaluationState = evaluationState,
        needsReview = needsReview,
        achievedAt = null,
        achievedVersion = null,
        linkedDebts = listOf(
            DebtGoalLinkViewDto(
                debtPublicId = "debt-a",
                status = "open",
                direction = "i_owe",
                counterpartyType = "external",
                counterpartyLabel = "招商信用卡",
                principalAmountCents = 100000,
                remainingAmountCents = 40000,
                homeCurrencyCode = "CNY",
            ),
            DebtGoalLinkViewDto(
                debtPublicId = "debt-b",
                status = "voided",
                direction = "owed_to_me",
                counterpartyType = "member",
                counterpartyLabel = "家人",
                principalAmountCents = 50000,
                remainingAmountCents = 50000,
                homeCurrencyCode = "CNY",
            ),
        ),
        voidedDebtPublicIds = listOf("debt-b"),
    ),
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
    override fun clearLastConfirmedSyncAtForLedger(ledgerId: String) = Unit
    override fun clearLedgerScopedRuntimeState() = Unit
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

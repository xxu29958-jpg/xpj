package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.BudgetAdviceInputsDto
import com.ticketbox.data.remote.dto.BudgetAdviseRequestDto
import com.ticketbox.data.remote.dto.BudgetAdviseResponseDto
import com.ticketbox.data.remote.dto.BudgetAdviceDto
import com.ticketbox.data.remote.dto.DiscretionaryResponseDto
import com.ticketbox.data.remote.dto.ExchangeRateListDto
import com.ticketbox.data.remote.dto.MonthlyArrangementDto
import com.ticketbox.data.remote.dto.MonthlyArrangementResponseDto
import com.ticketbox.data.remote.dto.MonthlyArrangementHistoryDto
import com.ticketbox.data.remote.dto.MonthlyArrangementHistoryItemDto
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.remote.dto.LifestyleStatsDto
import com.ticketbox.data.remote.dto.ReportsOverviewDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.SpendingGoalDetailViewModel
import com.ticketbox.viewmodel.SpendingGoalsViewModel
import com.ticketbox.viewmodel.SpendingGoalEditField
import com.ticketbox.viewmodel.MonthlyStatsViewModel
import com.ticketbox.viewmodel.StatsReportsViewModel
import com.ticketbox.viewmodel.DebtGoalViewModel
import com.ticketbox.viewmodel.BudgetAdviceViewModel
import com.ticketbox.viewmodel.editArrangement
import com.ticketbox.viewmodel.loadArrangementHistory
import com.ticketbox.viewmodel.refreshArrangement
import androidx.lifecycle.viewmodel.initializer
import androidx.lifecycle.viewmodel.viewModelFactory
import java.net.ConnectException
import java.util.concurrent.atomic.AtomicInteger
import kotlinx.coroutines.runBlocking
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response

/** The real list route opens a detail that was never requested before Room was reopened. */
class GoalOfflineReadingConnectedTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val mounted = mutableStateOf(false)
    @Volatile private var offline = false
    @Volatile private var denied = false
    private val detailCalls = AtomicInteger()
    private val original = GoalDto("offline-goal", "correction-ledger", "九月日元目标", "spending_limit",
        "monthly", "2026-09", null, 1200, null, null, null, "on_track", "active",
        "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z", 4, null, homeCurrencyCode = "JPY")
    private val debtGoal = original.copy(publicId = "offline-debt-goal", name = "还债计划", goalType = "debt_repayment")
    private val arrangement = MonthlyArrangementDto("correction-ledger", "2026-09", "JPY", 1200, 300, 4, "2026-09-01T00:00:00Z")
    private val harness = FactEntryNavigationHarness(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun goals(month: String?, includeArchived: Boolean, goalType: String?, timezone: String?): GoalListResponseDto {
                checkTransport()
                return GoalListResponseDto(listOf(if (goalType == "debt_repayment") debtGoal else original))
            }
            override suspend fun goal(publicId: String, timezone: String?): GoalDto {
                detailCalls.incrementAndGet()
                checkTransport()
                return if (publicId == debtGoal.publicId) debtGoal.copy(rowVersion = 5) else original.also { assertEquals(it.publicId, publicId) }
            }
            override suspend fun monthlyBudget(month: String, timezone: String?): BudgetMonthlyDto {
                checkTransport()
                return BudgetMonthlyDto("correction-ledger", month, true, 1200, 0, 0, 0, 1200, 0, 0, 1200, 0,
                    emptyList(), emptyList(), emptyList(), "2026-09-01T00:00:00Z", 4, "JPY")
            }
            override suspend fun monthlyStats(month: String?, tag: String?, timezone: String?, homeCurrencyCode: String?): MonthlyStatsDto {
                checkTransport()
                return MonthlyStatsDto("JPY", month = requireNotNull(month), totalAmountCents = 7000, count = 2, byCategory = emptyList())
            }
            override suspend fun lifestyleStats(month: String?, timezone: String?, homeCurrencyCode: String?): LifestyleStatsDto {
                checkTransport()
                return LifestyleStatsDto("JPY", month = requireNotNull(month), aiSubscriptionAmountCents = 100,
                    digitalAmountCents = 200, maxExpense = null, recent7DaysAmountCents = 300, frequentMerchants = emptyList())
            }
            override suspend fun reportsOverview(query: Map<String, String>): ReportsOverviewDto {
                checkTransport()
                return ReportsOverviewDto(query.getValue("month"), query.getValue("timezone"), "day", 7000, 2,
                    "2026-08", 3000, 1, "2025-09", 2000, 1, 5000, 1, null, "amount",
                    emptyList(), emptyList(), emptyList(), "JPY", emptyList())
            }
            override suspend fun monthlyArrangement(month: String): MonthlyArrangementResponseDto {
                checkTransport()
                return MonthlyArrangementResponseDto(arrangement.ledgerId, month, arrangement.copy(month = month))
            }
            override suspend fun monthlyArrangementHistory(month: String, beforeVersion: Long?, limit: Int): MonthlyArrangementHistoryDto {
                checkTransport()
                return MonthlyArrangementHistoryDto(arrangement.ledgerId, month,
                    listOf(MonthlyArrangementHistoryItemDto(4, arrangement.updatedAt, "JPY", 1200, 300)), null)
            }
            override suspend fun budgetAdviceInputs(month: String, timezone: String?, homeCurrencyCode: String?): BudgetAdviceInputsDto {
                checkTransport()
                return BudgetAdviceInputsDto(month, "JPY", DiscretionaryResponseDto(10000, 1000, 2000, 1200, 300, 5500),
                    emptyList(), savedArrangement = arrangement.copy(month = month))
            }
            override suspend fun exchangeRates(currencyCode: String?, homeCurrencyCode: String?, rateDate: String?, limit: Int): ExchangeRateListDto {
                checkTransport()
                return ExchangeRateListDto(emptyList())
            }
            override suspend fun budgetAdvise(request: BudgetAdviseRequestDto): BudgetAdviseResponseDto {
                checkTransport()
                return BudgetAdviseResponseDto(BudgetAdviceDto("保存计划建议", emptyList(), null), "JPY", "test",
                    inputs = budgetAdviceInputs(request.month, request.timezone, request.homeCurrencyCode))
            }
        }
    }
    private lateinit var list: SpendingGoalsViewModel

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun listReadSurvivesRoomReopenAndUnvisitedDetailThenRefusalClearsOnlyReadData() {
        val pending = prepare()
        show()
        openCachedDetail()
        val detail = detailModel()
        assertEquals("JPY", detail.state.value.goal?.homeCurrencyCode)
        assertNull(detail.state.value.goal?.progress)
        assertNotNull(detail.state.value.fetchedAt)
        assertTrue(detail.state.value.fromCache)
        compose.onNodeWithText(context.getString(R.string.spending_goal_progress_unavailable)).performScrollTo().assertIsDisplayed()
        compose.onNodeWithTag("goal-read-source").assertIsDisplayed()
        denied = true
        compose.runOnIdle { detail.load() }
        compose.waitUntil(5_000) { !detail.state.value.isLoading && detail.state.value.loadError != null }
        assertNull(detail.state.value.goal)
        assertNull(detail.state.value.fetchedAt)
        compose.onNodeWithTag("goal-read-source").assertDoesNotExist()
        assertEquals(pending, harness.fixture.stored())
        denied = false
        compose.runOnIdle { detail.load() }
        compose.waitUntil(5_000) { !detail.state.value.isLoading }
        assertNull(detail.state.value.goal)
    }

    @Test fun replacingBindingHidesTheOriginalSnapshotAndPreservesTheOriginalOutbox() {
        val pending = prepare()
        show()
        openCachedDetail()
        val detail = detailModel()
        compose.runOnIdle { harness.fixture.switchLedger() }
        compose.waitUntil(5_000) { detail.state.value.goal == null && !detail.state.value.isLoading }
        assertNull(detail.state.value.fetchedAt)
        assertTrue(list.state.value.goals.isEmpty())
        assertEquals(pending, harness.fixture.stored())
        compose.onNodeWithTag("goal-read-source").assertDoesNotExist()
    }

    @Test fun oneBudgetRefusalWithdrawsRetainedStatsAndGoalReadersWithoutChangingTheDirtyDraftOrOutbox() {
        runBlocking { harness.saveFailedCorrection() }
        val rows = harness.fixture.stored()
        val graph = harness.fixture.graph
        lateinit var monthly: MonthlyStatsViewModel
        lateinit var reports: StatsReportsViewModel
        lateinit var debt: DebtGoalViewModel
        lateinit var cleanDetail: SpendingGoalDetailViewModel
        lateinit var dirtyDetail: SpendingGoalDetailViewModel
        compose.runOnIdle {
            val factory = viewModelFactory {
                initializer { MonthlyStatsViewModel(graph.expenseRepository, "2026-09") }
                initializer { StatsReportsViewModel(graph.reportsRepository) }
                initializer { SpendingGoalsViewModel(graph.reportsRepository, graph.goalEditRepository, "2026-09") }
                initializer { SpendingGoalDetailViewModel(graph.reportsRepository, graph.goalEditRepository) }
                initializer { DebtGoalViewModel(graph.reportsRepository, graph.debtWriteRepository) }
            }
            val models = ViewModelProvider(harness.models, factory)
            monthly = models[MonthlyStatsViewModel::class.java]
            reports = models[StatsReportsViewModel::class.java]
            list = models[SpendingGoalsViewModel::class.java]
            debt = models[DebtGoalViewModel::class.java]
            cleanDetail = models["clean-detail", SpendingGoalDetailViewModel::class.java]
            dirtyDetail = models["dirty-detail", SpendingGoalDetailViewModel::class.java]
        }
        compose.waitUntil(5_000) {
            monthly.uiState.value.lifestyleStats != null && list.state.value.goals.isNotEmpty() && debt.state.value.goals.isNotEmpty()
        }
        compose.runOnIdle { reports.refresh("2026-09", "") }
        compose.waitUntil(5_000) { reports.uiState.value.reportGoals.isNotEmpty() }
        assertNotNull(reports.uiState.value.reportsOverview)
        compose.runOnIdle { cleanDetail.load(original.publicId) }
        compose.waitUntil(5_000) { cleanDetail.state.value.goal != null }
        compose.runOnIdle { dirtyDetail.load(original.publicId) }
        compose.waitUntil(5_000) { dirtyDetail.state.value.goal != null }
        compose.runOnIdle {
            debt.openDetail(debt.state.value.goals.single())
            cleanDetail.beginEdit()
            dirtyDetail.beginEdit()
            dirtyDetail.updateField(SpendingGoalEditField.Amount, "2345")
        }
        compose.waitUntil(5_000) { debt.state.value.selectedGoal?.rowVersion == 5L }
        val dirty = dirtyDetail.state.value
        val detailReads = detailCalls.get()
        denied = true
        assertEquals(403, runBlocking { graph.budgetRepository.monthlyBudget("2026-09") }
            .exceptionOrNull().let { (it as? com.ticketbox.data.repository.RepositoryException)?.httpStatusCode })
        compose.waitForIdle()
        assertNull(dirtyDetail.state.value.goal)
        assertEquals(dirty.name, dirtyDetail.state.value.name)
        assertEquals("2345", dirtyDetail.state.value.targetAmountInput)
        assertEquals(dirty.pendingEdits, dirtyDetail.state.value.pendingEdits)
        assertEquals(detailReads, detailCalls.get())
        assertEquals(rows, harness.fixture.stored())
        assertRetainedReadersWithdrawAndRecover(monthly, reports, debt, cleanDetail, dirtyDetail)
        assertEquals("2345", dirtyDetail.state.value.targetAmountInput)
        assertEquals(rows, harness.fixture.stored())
    }

    private fun assertRetainedReadersWithdrawAndRecover(monthly: MonthlyStatsViewModel, reports: StatsReportsViewModel,
        debt: DebtGoalViewModel, cleanDetail: SpendingGoalDetailViewModel, dirtyDetail: SpendingGoalDetailViewModel) {
        assertNull("Retained monthly statistics must be withdrawn without a refresh", monthly.uiState.value.stats)
        assertNull(monthly.uiState.value.statsFetchedAt)
        assertNull(monthly.uiState.value.lifestyleStats)
        assertNull(monthly.uiState.value.lifestyleFetchedAt)
        assertTrue(reports.uiState.value.reportGoals.isEmpty())
        assertNull(reports.uiState.value.reportGoalsFetchedAt)
        assertNull(reports.uiState.value.reportsOverview)
        assertTrue(list.state.value.goals.isEmpty())
        assertNull(list.state.value.fetchedAt)
        assertTrue(debt.state.value.goals.isEmpty())
        assertNull(debt.state.value.selectedGoal)
        assertNull(debt.state.value.selectedFetchedAt)
        assertNull(cleanDetail.state.value.goal)
        assertNull(cleanDetail.state.value.fetchedAt)
        assertEquals("", cleanDetail.state.value.name)
        assertEquals("", cleanDetail.state.value.targetAmountInput)
        assertEquals("", cleanDetail.state.value.category)
        denied = false
        compose.runOnIdle {
            monthly.refresh(); list.refresh(); debt.refresh()
        }
        compose.waitUntil(5_000) {
            monthly.uiState.value.stats != null && list.state.value.goals.isNotEmpty() && debt.state.value.goals.isNotEmpty()
        }
        compose.runOnIdle { reports.refresh("2026-09", "") }
        compose.waitUntil(5_000) { reports.uiState.value.reportGoals.isNotEmpty() }
        compose.runOnIdle { cleanDetail.load() }
        compose.waitUntil(5_000) { cleanDetail.state.value.goal != null }
        assertTrue(!cleanDetail.state.value.fromCache)
        compose.runOnIdle { dirtyDetail.load() }
        compose.waitUntil(5_000) { dirtyDetail.state.value.goal != null }
        assertTrue(!dirtyDetail.state.value.fromCache)
    }

    @Test fun oneBudgetRefusalWithdrawsRetainedArrangementHistoryAdviceAndOnlyTheUneditedServerForm() {
        runBlocking { harness.saveFailedCorrection() }
        val rows = harness.fixture.stored()
        val graph = harness.fixture.graph
        lateinit var clean: BudgetAdviceViewModel
        lateinit var dirty: BudgetAdviceViewModel
        compose.runOnIdle {
            val models = ViewModelProvider(harness.models, viewModelFactory {
                initializer { BudgetAdviceViewModel(graph.budgetRepository, "2026-09") }
            })
            clean = models["clean-advice", BudgetAdviceViewModel::class.java]
            dirty = models["dirty-advice", BudgetAdviceViewModel::class.java]
        }
        compose.waitUntil(5_000) { clean.uiState.value.inputs != null && dirty.uiState.value.arrangementDraft != null }
        compose.runOnIdle {
            clean.requestAdvice()
            clean.loadArrangementHistory()
            dirty.loadArrangementHistory()
        }
        compose.waitUntil(5_000) {
            clean.uiState.value.result?.advice != null && clean.uiState.value.arrangementHistory.isNotEmpty() &&
                dirty.uiState.value.arrangementHistory.isNotEmpty()
        }
        compose.runOnIdle { dirty.editArrangement(savings = true, value = "3456") }
        val draft = requireNotNull(dirty.uiState.value.arrangementDraft)
        val binding = requireNotNull(dirty.uiState.value.binding)
        compose.waitUntil(5_000) { runBlocking { graph.budgetRepository.arrangementDraft(binding, "2026-09") } == draft }
        assertNotNull(clean.uiState.value.result?.advice)
        assertTrue(clean.uiState.value.arrangementDraft?.edited == false)
        denied = true
        assertEquals(403, runBlocking { graph.budgetRepository.monthlyBudget("2026-09") }
            .exceptionOrNull().let { (it as? com.ticketbox.data.repository.RepositoryException)?.httpStatusCode })
        compose.waitForIdle()
        assertNull("Retained arrangement must be withdrawn without a refresh", clean.uiState.value.arrangementRead)
        assertTrue(clean.uiState.value.arrangementHistory.isEmpty())
        assertNull(clean.uiState.value.arrangementHistoryNext)
        assertNull(clean.uiState.value.arrangementDraft)
        assertNull(clean.uiState.value.inputs)
        assertNull(clean.uiState.value.result)
        assertNull(clean.uiState.value.trialRequest)
        assertNull(dirty.uiState.value.arrangementRead)
        assertTrue(dirty.uiState.value.arrangementHistory.isEmpty())
        assertEquals(draft, dirty.uiState.value.arrangementDraft)
        assertEquals(draft, runBlocking { graph.budgetRepository.arrangementDraft(binding, "2026-09") })
        assertEquals(rows, harness.fixture.stored())
        denied = false
        compose.runOnIdle { clean.refreshArrangement(); clean.loadArrangementHistory(); dirty.refreshArrangement() }
        compose.waitUntil(5_000) { clean.uiState.value.inputs != null && clean.uiState.value.arrangementHistory.isNotEmpty() &&
            dirty.uiState.value.arrangementRead != null }
        assertTrue(clean.uiState.value.arrangementRead?.fromCache == false)
        assertTrue(!clean.uiState.value.arrangementHistoryCached)
        assertEquals(draft, dirty.uiState.value.arrangementDraft)
        assertEquals(rows, harness.fixture.stored())
    }

    private fun prepare(): List<Map<String, String?>> {
        runBlocking {
            harness.fixture.graph.reportsRepository.goals("2026-09").getOrThrow()
            harness.saveFailedCorrection()
        }
        assertEquals(0, detailCalls.get())
        val originalRows = harness.fixture.stored()
        offline = true
        harness.fixture.reopen()
        return originalRows
    }

    private fun show() {
        val graph = harness.fixture.graph
        val factory = MainScreenFactory(harness.screenFactory.repositories.copy(
            reportsRepository = graph.reportsRepository, goalEditRepository = graph.goalEditRepository,
        ), harness.screenFactory.viewModelFactories)
        compose.runOnIdle {
            list = ViewModelProvider(harness.models, viewModelFactory {
                initializer { SpendingGoalsViewModel(graph.reportsRepository, graph.goalEditRepository, "2026-09") }
            })["spending-goals", SpendingGoalsViewModel::class.java]
            ViewModelProvider(harness.models, viewModelFactory {
                initializer { com.ticketbox.viewmodel.CreateSpendingGoalViewModel(graph.goalEditRepository) }
            })["create-spending-goal", com.ticketbox.viewmodel.CreateSpendingGoalViewModel::class.java]
            mounted.value = true
        }
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models,
                    LocalCurrencyDisplay provides CurrencyDisplay(CurrencyCode.CNY)) {
                    if (mounted.value) SpendingGoalsRoute(factory, onBack = {}, creationOwner = harness.models)
                }
            }
        }
    }

    private fun openCachedDetail() {
        compose.waitUntil(5_000) { list.state.value.fromCache && !list.state.value.isLoading }
        compose.onNodeWithText(original.name).performScrollTo().performClick()
        compose.waitForIdle()
        val detail = detailModel()
        compose.waitUntil(5_000) { detail.state.value.goal != null && !detail.state.value.isLoading }
        compose.waitUntil(5_000) { compose.onAllNodes(hasTestTag("goal-read-source")).fetchSemanticsNodes().isNotEmpty() }
    }

    private fun detailModel() = ViewModelProvider(harness.models)["spending-goal-detail", SpendingGoalDetailViewModel::class.java]

    private fun checkTransport() {
        if (denied) throw HttpException(Response.error<Any>(403, "{}".toResponseBody()))
        if (offline) throw ConnectException("Synthetic unavailable transport")
    }
}

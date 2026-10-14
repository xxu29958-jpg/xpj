package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.navigation.NavHostController
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.DashboardCardDto
import com.ticketbox.data.remote.dto.DashboardCardsResponseDto
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import com.ticketbox.data.remote.dto.MonthsDto
import com.ticketbox.data.remote.dto.MonthlyArrangementDto
import com.ticketbox.data.remote.dto.MonthlyArrangementResponseDto
import com.ticketbox.data.remote.dto.MonthlyArrangementSaveRequest
import com.ticketbox.data.remote.dto.BudgetAdviceInputsDto
import com.ticketbox.data.remote.dto.DiscretionaryResponseDto
import com.ticketbox.data.repository.MonthlyArrangementDraft
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.DASHBOARD_CARD_BUDGET
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.domain.model.CurrencyDisplay
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.assertIsNotEnabled
import java.time.YearMonth
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Real nested product navigation; controlled transport supplies two distinct task months. */
class BudgetRecoveryNavigationRouteTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val currentMonth = YearMonth.now()
    private val originalMonth = currentMonth.minusMonths(2).toString()
    private val transport = BudgetNavigationTransport(currentMonth.toString(), originalMonth)
    private val harness = FactEntryNavigationHarness(context, transport::wrap)
    private val mounted = mutableStateOf(true)
    private lateinit var outer: NavHostController

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun obligationOriginalSubmissionOpensItsOwnBudgetMonth() {
        openOriginalBudget(fromWorkspace = false)
    }

    @Test fun workspaceOriginalSubmissionOpensItsOwnBudgetMonth() {
        openOriginalBudget(fromWorkspace = true)
    }

    @Test fun readOnlyObligationArrangementConflictOpensItsOriginalMonthWithoutChangingItsCommandOrNewerDraft() {
        openOriginalArrangement(fromWorkspace = false, readOnly = true)
    }

    @Test fun workspaceArrangementConflictOpensItsOriginalMonthWithoutChangingItsCommandOrNewerDraft() {
        openOriginalArrangement(fromWorkspace = true)
    }

    private fun openOriginalArrangement(fromWorkspace: Boolean, readOnly: Boolean = false) {
        val repository = harness.screenFactory.budgetRepository
        val draft = MonthlyArrangementDraft("JPY", "8000", "750", 2, true)
        val binding = runBlocking {
            val binding = requireNotNull(harness.fixture.graph.expenseRepository.captureDeferredLedgerBinding())
            val id = repository.enqueueArrangement(binding, originalMonth,
                MonthlyArrangementSaveRequest("JPY", 3000, 500, 1)).getOrThrow()
            harness.fixture.outbox.markConflict(id, "monthly_arrangement_row_version_conflict")
            repository.storeArrangementDraft(binding, originalMonth, draft)
            binding
        }
        val original = harness.fixture.stored().single()
        if (readOnly) harness.fixture.role("viewer")
        val summary = context.getString(R.string.arrangement_original, originalMonth, 1,
            formatDisplayAmount(3000, CurrencyDisplay.forRecord("JPY")),
            formatDisplayAmount(500, CurrencyDisplay.forRecord("JPY")))
        show()
        if (fromWorkspace) {
            compose.runOnIdle { harness.shell.openAccount() }
            val settingsGroup = context.getString(R.string.settings_root_sync_directory_title)
            waitForText(settingsGroup)
            compose.onNodeWithText(settingsGroup).performScrollTo().performClick()
            val entry = context.getString(R.string.settings_root_entry_offline_sync_title)
            waitForText(entry)
            compose.onNodeWithText(entry).performScrollTo().performClick()
        } else compose.runOnIdle { harness.shell.openSecondaryPage(ProductSecondaryPage.ObligationSync) }
        val recoveryEntry = context.getString(R.string.sync_status_review_entry_hint)
        waitForText(recoveryEntry)
        compose.onNodeWithText(recoveryEntry).performScrollTo().performClick()
        waitForText(summary)
        compose.onNodeWithText(summary).performScrollTo().assertIsDisplayed()
        val action = context.getString(R.string.arrangement_open_month)
        waitForText(action)
        compose.onNodeWithText(action).performScrollTo().performClick()
        waitForText(context.getString(R.string.budget_advice_page_title))
        compose.waitUntil(5_000) { transport.arrangementReads.lastOrNull() == originalMonth }
        waitForText(summary)
        compose.onNodeWithText(summary).performScrollTo().assertIsDisplayed()
        compose.onNode(hasSetTextAction() and hasAnyAncestor(hasTestTag("arrangement_savings")), useUnmergedTree = true)
            .performScrollTo().assertTextEquals("8000")
        val review = compose.onNodeWithText(context.getString(R.string.arrangement_review)).performScrollTo()
        review.assertIsDisplayed()
        if (readOnly) review.assertIsNotEnabled()
        compose.onNodeWithText(context.getString(R.string.arrangement_save)).assertIsDisplayed().assertIsNotEnabled()
        assertEquals(MainProductDestination.Secondary(ProductSecondaryPage.BudgetAdvice), harness.shell.activeDestination)
        assertEquals(MAIN_ROUTE, outer.currentBackStackEntry?.destination?.route)
        assertEquals("Opening must preserve the original key, body, binding, OCC and Conflict", original,
            harness.fixture.stored().single())
        assertEquals(draft, runBlocking { repository.arrangementDraft(binding, originalMonth) })
        assertEquals(originalMonth, transport.arrangementReads.last())
        transport.budgetConfigured = true
        val budgetReadsBefore = transport.budgetReads.size
        compose.onNodeWithText(context.getString(R.string.arrangement_budget_open)).performScrollTo().performClick()
        assertBudgetMonth(budgetReadsBefore)
        transport.budgetRevision = 4
        androidx.test.espresso.Espresso.pressBack()
        waitForText(context.getString(R.string.budget_advice_page_title))
        waitForText(context.getString(R.string.arrangement_budget_version, 4))
        compose.onNode(hasSetTextAction() and hasAnyAncestor(hasTestTag("arrangement_savings")), useUnmergedTree = true)
            .performScrollTo().assertTextEquals("8000")
        assertEquals(draft, runBlocking { repository.arrangementDraft(binding, originalMonth) })
        assertEquals(original, harness.fixture.stored().single())
        if (!readOnly) {
            review.performScrollTo().performClick()
            waitForText(context.getString(R.string.arrangement_reviewed))
            compose.onNodeWithText(context.getString(R.string.arrangement_save)).assertIsDisplayed().assertIsNotEnabled()
            assertEquals(original, harness.fixture.stored().single())
            val reviewed = MonthlyArrangementDraft("JPY", "3000", "500", 2, true)
            compose.waitUntil(5_000) { runBlocking { repository.arrangementDraft(binding, originalMonth) == reviewed } }
        }
    }

    @Test fun insightsHistoricalMonthBudgetActionKeepsTheSelectedMonth() {
        verifyInsightsHistoricalMonthBudgetAction(configured = false)
    }

    @Test fun configuredInsightsBudgetStillOpensTheSelectedHistoricalMonth() {
        verifyInsightsHistoricalMonthBudgetAction(configured = true)
    }

    @Test fun insightsRateRepairUsesTheProductGraphAndReturnsToItsOriginalMonth() {
        val gap = com.ticketbox.data.remote.dto.MissingExchangeRateDto("USD", "CNY", "$originalMonth-05")
        transport.rateGap = gap
        openHistoricalInsights()
        compose.onNodeWithText(context.getString(R.string.stats_tab_trend)).performClick()
        val action = context.getString(R.string.reports_repair_rates)
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(action))
        compose.onNodeWithText(action).performScrollTo().performClick()
        assertReportRateMonth()
        saveConsumerArtPreview("insights-rate-directory", compose.onRoot().captureToImage().asAndroidBitmap())
        androidx.test.espresso.Espresso.pressBack()
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(context.getString(R.string.stats_tab_trend)))
        assertEquals(MainProductDestination.Domain(PrimaryDomain.Insights), harness.shell.activeDestination)
        for (prefix in listOf("report-rate", "stats-rate")) {
            if (prefix == "stats-rate") compose.onNodeWithText(context.getString(R.string.stats_tab_overview)).performClick()
            val tag = "$prefix-USD-${gap.rateDate}"
            compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasTestTag(tag))
            compose.onNode(hasTestTag(tag)).performClick()
            assertReportRateMonth()
            compose.waitUntil(5_000) { transport.rateReads.contains(Triple("USD", "CNY", gap.rateDate)) }
            compose.onNodeWithText(context.getString(R.string.advice_reference_manual)).performScrollTo().assertIsDisplayed()
            saveConsumerArtPreview("insights-$prefix-editor", compose.onRoot().captureToImage().asAndroidBitmap())
            androidx.test.espresso.Espresso.pressBack()
            compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(context.getString(R.string.stats_tab_overview)))
            assertEquals(MainProductDestination.Domain(PrimaryDomain.Insights), harness.shell.activeDestination)
        }
        val historical = YearMonth.parse(originalMonth)
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(context.getString(
            R.string.components_month_label, historical.year.toString(), historical.monthValue.toString())))
        assertEquals(originalMonth, transport.budgetReads.last())
        assertTrue(harness.fixture.stored().isEmpty())
    }

    private fun assertReportRateMonth() {
        waitForText(context.getString(R.string.advice_reference_page_title))
        compose.waitUntil(5_000) { transport.adviceInputReads.lastOrNull() == (originalMonth to "CNY") }
        assertEquals(MainProductDestination.Secondary(ProductSecondaryPage.BudgetAdvice), harness.shell.activeDestination)
        assertEquals(MAIN_ROUTE, outer.currentBackStackEntry?.destination?.route)
    }

    private fun verifyInsightsHistoricalMonthBudgetAction(configured: Boolean) {
        transport.budgetConfigured = configured
        openHistoricalInsights()
        val action = context.getString(if (configured) R.string.stats_budget_open_action else R.string.stats_budget_empty_action)
        waitForText(action)
        val readsBeforeOpen = transport.budgetReads.size

        compose.onNodeWithText(action).performScrollTo().performClick()

        assertBudgetMonth(readsBeforeOpen)
        assertTrue(harness.fixture.stored().isEmpty())
    }

    private fun openHistoricalInsights() {
        show()
        compose.runOnIdle { harness.shell.selectPrimaryDomain(PrimaryDomain.Insights.key) }
        val monthLabel = context.getString(R.string.components_month_label,
            currentMonth.year.toString(), currentMonth.monthValue.toString())
        waitForText(monthLabel)
        compose.onNode(hasText(monthLabel) and hasClickAction()).performScrollTo().performClick()
        val historical = YearMonth.parse(originalMonth)
        val historicalLabel = context.getString(R.string.components_month_label,
            historical.year.toString(), historical.monthValue.toString())
        waitForText(historicalLabel)
        compose.onNode(hasText(historicalLabel) and hasClickAction()).performScrollTo().performClick()
        compose.waitUntil(5_000) { transport.budgetReads.lastOrNull() == originalMonth }
    }

    private fun openOriginalBudget(fromWorkspace: Boolean) {
        runBlocking {
            val binding = requireNotNull(harness.fixture.graph.expenseRepository.captureDeferredLedgerBinding())
            val id = harness.screenFactory.budgetRepository.enqueueSave(binding, originalMonth,
                BudgetMonthlyUpdate("CNY", null, 3100)).getOrThrow()
            harness.fixture.outbox.markFailed(id, "budget_delivery_unknown")
        }
        val original = harness.fixture.stored().single()
        show()
        if (fromWorkspace) {
            compose.runOnIdle { harness.shell.openAccount() }
            val settingsGroup = context.getString(R.string.settings_root_sync_directory_title)
            waitForText(settingsGroup)
            compose.onNodeWithText(settingsGroup).performScrollTo().performClick()
            val entry = context.getString(R.string.settings_root_entry_offline_sync_title)
            waitForText(entry)
            compose.onNodeWithText(entry).performScrollTo().performClick()
        } else {
            compose.runOnIdle { harness.shell.openSecondaryPage(ProductSecondaryPage.ObligationSync) }
        }
        val action = context.getString(R.string.budget_save_open_month)
        waitForText(action)
        val readsBeforeOpen = transport.budgetReads.size

        compose.onNodeWithText(action).performScrollTo().performClick()

        assertBudgetMonth(readsBeforeOpen)
        assertEquals("Opening the original must not replace, retry, or settle it", original,
            harness.fixture.stored().single())
    }

    private fun assertBudgetMonth(readsBeforeOpen: Int) {
        compose.waitUntil(5_000) { transport.budgetReads.size > readsBeforeOpen }
        assertEquals(originalMonth, transport.budgetReads.last())
        assertEquals(MainProductDestination.Secondary(ProductSecondaryPage.Budget), harness.shell.activeDestination)
        assertEquals(MAIN_ROUTE, outer.currentBackStackEntry?.destination?.route)
        // Cached and fresh reads have distinct headers but the same task-month selector.
        val monthLabel = YearMonth.parse(originalMonth).let {
            context.getString(R.string.components_month_label, it.year.toString(), it.monthValue.toString())
        }
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(monthLabel))
        compose.onNodeWithText(monthLabel).assertIsDisplayed()
    }

    private fun show() {
        compose.setContent {
            if (mounted.value) CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Paper) {
                    outer = rememberNavController()
                    MainNavGraph(MainNavigationRuntime(outer, harness.shell, harness.screenFactory),
                        remember { SnackbarHostState() },
                        SettingsPreferenceControls(AppSkin.Paper, AppThemeMode.System, CurrencyCode.CNY,
                            onThemeModeChange = {}, onCurrencyChange = {}),
                        onBindingCleared = { error("Opening the original must preserve its binding") })
                }
            }
        }
        compose.waitForIdle()
    }

    private fun waitForText(text: String) {
        compose.waitUntil(5_000) { compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty() }
    }
}

internal class BudgetNavigationTransport(private val currentMonth: String, private val originalMonth: String) {
    var budgetConfigured = false
    var backupReads = 0
    val budgetReads = CopyOnWriteArrayList<String>()
    val arrangementReads = CopyOnWriteArrayList<String>()
    val adviceInputReads = CopyOnWriteArrayList<Pair<String, String?>>()
    val rateReads = CopyOnWriteArrayList<Triple<String?, String?, String?>>()
    var rateGap: com.ticketbox.data.remote.dto.MissingExchangeRateDto? = null
    var budgetRevision = 1L

    fun wrap(delegate: ApiService): ApiService = object : ApiService by delegate {
        override suspend fun privateStatus(): com.ticketbox.data.remote.dto.StatusPrivateDto {
            backupReads += 1
            return com.ticketbox.data.remote.dto.StatusPrivateDto("ok", backupStale = true)
        }

        override suspend fun monthlyArrangement(month: String): MonthlyArrangementResponseDto {
            arrangementReads += month
            return MonthlyArrangementResponseDto("correction-ledger", month,
                MonthlyArrangementDto("correction-ledger", month, "JPY", 4000, 600, 2, "2026-09-27T00:00:00Z"))
        }

        override suspend fun budgetAdviceInputs(month: String, timezone: String?, homeCurrencyCode: String?): BudgetAdviceInputsDto {
            adviceInputReads += month to homeCurrencyCode
            return BudgetAdviceInputsDto(month, homeCurrencyCode ?: "JPY",
                DiscretionaryResponseDto(10000, 1000, 2000, 4000, 600, 2400, 0), emptyList(),
                budgetDefinition = if (!budgetConfigured) null else com.ticketbox.data.remote.dto.BudgetPlanDefinitionDto(
                    "CNY", 10000, 0, 0, emptyList(), budgetRevision, "2026-10-11T04:00:00Z"),
                dataScope = com.ticketbox.data.remote.dto.BudgetAdviceDataScopeDto("2026-10-11T04:00:00Z",
                    YearMonth.parse(month).minusMonths(6).toString(), YearMonth.parse(month).minusMonths(1).toString(), 0))
        }

        override suspend fun reportsOverview(query: Map<String, String>): com.ticketbox.data.remote.dto.ReportsOverviewDto {
            if (rateGap == null) return delegate.reportsOverview(query)
            val month = YearMonth.parse(query.getValue("month"))
            return com.ticketbox.data.remote.dto.ReportsOverviewDto(month.toString(), "UTC", "day", null, 1,
                month.minusMonths(1).toString(), 0, 0, month.minusYears(1).toString(), 0, 0, null, null,
                null, "amount", emptyList(), emptyList(), emptyList(), "CNY", listOfNotNull(rateGap))
        }

        override suspend fun exchangeRates(currencyCode: String?, homeCurrencyCode: String?, rateDate: String?, limit: Int): com.ticketbox.data.remote.dto.ExchangeRateListDto {
            rateReads += Triple(currencyCode, homeCurrencyCode, rateDate)
            return com.ticketbox.data.remote.dto.ExchangeRateListDto(emptyList())
        }

        override suspend fun referenceRates(homeCurrencyCode: String, currencyCode: String?, rateDate: String?) =
            com.ticketbox.data.remote.dto.ReferenceRatesDto("frankfurter", true, "waiting", rateDate, items = emptyList())

        override suspend fun months(timezone: String?) = MonthsDto(listOf(currentMonth, originalMonth))

        override suspend fun monthlyStats(month: String?, tag: String?, timezone: String?, homeCurrencyCode: String?) =
            MonthlyStatsDto(homeCurrencyCode = "CNY", month = requireNotNull(month),
                totalAmountCents = 1000, count = 1, byCategory = emptyList(), missingRates = listOfNotNull(rateGap))

        override suspend fun dashboardCards(surface: String) = DashboardCardsResponseDto(surface,
            listOf(DashboardCardDto(DASHBOARD_CARD_BUDGET, "预算", true, 0)))

        override suspend fun monthlyBudget(month: String, timezone: String?): BudgetMonthlyDto {
            budgetReads += month
            val amount = if (budgetConfigured) 10000L else 0L
            return BudgetMonthlyDto(ledgerId = "correction-ledger", month = month, configured = budgetConfigured,
                homeCurrencyCode = "CNY", rowVersion = if (budgetConfigured) 1 else null, totalAmountCents = amount, rolloverAmountCents = 0,
                fixedAmountCents = 0, nonMonthlyAmountCents = 0, flexBudgetCents = amount, spentAmountCents = 0,
                excludedAmountCents = 0, remainingAmountCents = amount, overspentAmountCents = 0,
                excludedCategories = emptyList(), excludedBreakdown = emptyList(), categoryBudgets = emptyList(),
                updatedAt = null)
        }
    }
}

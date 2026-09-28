package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.semantics.getOrNull
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.SemanticsMatcher
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BudgetCategoryDto
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.LedgerCalendarDto
import com.ticketbox.data.remote.dto.DashboardCardDto
import com.ticketbox.data.remote.dto.DashboardCardsResponseDto
import com.ticketbox.data.remote.dto.MonthsDto
import com.ticketbox.data.repository.newTaskMonth
import com.ticketbox.data.repository.budgetHistoryPage
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.BudgetMonthlyUpdate
import com.ticketbox.domain.model.DASHBOARD_CARD_BUDGET
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.ui.saveConsumerArtPreview
import java.net.ConnectException
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.runBlocking
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response

/** MainNavGraph -> actual Plan card -> BudgetRoute, across a real disk Room/VM reopen. */
class BudgetOfflineReadingConnectedTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val transport = OfflineBudgetTransport()
    private val harness = FactEntryNavigationHarness(context, transport::wrap)
    private val mounted = mutableStateOf(true)

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun aPreviouslyReadBudgetIsReachableFromPlansAfterRoomAndViewModelsReopenOffline() {
        // The entry uses the current month; fixed September and unvisited October are tested separately.
        val calendars = harness.fixture.ledgerCalendarRepository
        val month = runBlocking {
            calendars.refresh(requireNotNull(calendars.currentBinding())).getOrThrow()
            calendars.newTaskMonth()
        }
        transport.uiMonth = month
        runBlocking {
            harness.saveFailedCorrection()
            val binding = requireNotNull(calendars.currentBinding())
            val id = harness.fixture.graph.budgetRepository.enqueueSave(binding, month,
                BudgetMonthlyUpdate("JPY", 7, 1200)).getOrThrow()
            harness.fixture.outbox.markFailed(id, "budget_delivery_unknown")
        }
        val originalIntent = harness.fixture.stored()
        showPlans()
        compose.waitUntil(5_000) { transport.reads.contains(month) }
        waitForAmount()
        compose.onNodeWithText("¥789").assertIsDisplayed()
        val originalReadTime = readTime()

        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        transport.offline = true
        harness.fixture.reopen()
        val previousReads = transport.reads.size
        compose.runOnIdle { mounted.value = true }
        compose.waitForIdle()
        compose.runOnIdle { harness.shell.selectPrimaryDomain(PrimaryDomain.Plans.key) }
        compose.waitUntil(5_000) { transport.reads.size > previousReads }
        waitForAmount()

        // Existing production loses this amount on reopen; no new model API is required to expose the gap.
        compose.onNodeWithText("¥789").assertIsDisplayed()
        preview("budget-offline-plans")
        compose.onNodeWithTag("plan_destination_budget").performScrollTo().performClick()
        compose.waitUntil(5_000) { compose.onAllNodes(hasTestTag("budget_total_amount"))
            .fetchSemanticsNodes().isNotEmpty() }
        // The original queued command locks editing; disabled fields retain text but have no SetText action.
        val originalAmount = SemanticsMatcher.keyIsDefined(SemanticsProperties.EditableText) and
            hasAnyAncestor(hasTestTag("budget_total_amount"))
        compose.waitUntil(5_000) { compose.onAllNodes(originalAmount and hasText("1200"), useUnmergedTree = true)
            .fetchSemanticsNodes().isNotEmpty() }
        compose.onNode(originalAmount, useUnmergedTree = true).performScrollTo()
            .assertTextEquals("1200").assertIsNotEnabled()
        compose.onNodeWithTag("budget-read-source").performScrollTo().assertIsDisplayed()
        assertNotNull("The online read must expose its actual read time", originalReadTime)
        assertEquals("Reopening must not manufacture a new fetch time", originalReadTime, readTime())
        assertTrue(sourceText().contains("离线"))
        preview("budget-offline-editor")

        compose.runOnIdle { harness.shell.selectPrimaryDomain(PrimaryDomain.Insights.key) }
        compose.waitUntil(5_000) { compose.onAllNodes(hasTestTag("overview-module-budget"))
            .fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("overview-module-budget").performScrollTo().assertIsDisplayed()
        val remaining = context.getString(com.ticketbox.R.string.stats_budget_progress_remaining, "¥789")
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(remaining)).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText(remaining).performScrollTo().assertIsDisplayed()
        compose.onNodeWithTag("budget-read-source").performScrollTo().assertIsDisplayed()
        assertEquals("Insights must identify the same saved query", originalReadTime, readTime())
        assertTrue(sourceText().contains("离线"))
        assertEquals(originalIntent, harness.fixture.stored())
        preview("budget-offline-insights")
    }

    private fun preview(name: String) {
        compose.waitForIdle()
        saveConsumerArtPreview(name, requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
    }

    @Test fun realBudgetHistoryReopensOfflineWithItsOriginalTimeAndOlderPages() {
        val calendars = harness.fixture.ledgerCalendarRepository
        val month = runBlocking {
            calendars.refresh(requireNotNull(calendars.currentBinding())).getOrThrow()
            calendars.newTaskMonth()
        }
        transport.uiMonth = month
        showPlans()
        waitForAmount()
        openBudgetHistory()
        val originalTime = readTime("budget-history-read-source")
        assertNotNull(originalTime)
        compose.onNodeWithText(context.getString(R.string.budget_history_more)).performScrollTo().performClick()
        compose.waitUntil(5_000) { compose.onAllNodes(hasText("餐饮 · ¥50")).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("餐饮 · ¥50").performScrollTo().assertIsDisplayed()
        val pending = harness.fixture.stored()
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        transport.offline = true
        harness.fixture.reopen()
        compose.runOnIdle { mounted.value = true }
        compose.waitForIdle()
        compose.runOnIdle { harness.shell.selectPrimaryDomain(PrimaryDomain.Plans.key) }
        waitForAmount()
        openBudgetHistory()
        assertEquals(originalTime, readTime("budget-history-read-source"))
        assertTrue(sourceText("budget-history-read-source").contains("本机保留"))
        compose.onNodeWithText(context.getString(R.string.budget_history_more)).performScrollTo().performClick()
        compose.waitUntil(5_000) { compose.onAllNodes(hasText("餐饮 · ¥50")).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("餐饮 · ¥50").performScrollTo().assertIsDisplayed()
        compose.onNodeWithTag("budget-history-read-source").performScrollTo().assertIsDisplayed()
        preview("budget-history-offline-reopened")
        assertEquals(pending, harness.fixture.stored())
    }

    private fun openBudgetHistory() {
        compose.onNodeWithTag("plan_destination_budget").performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.budget_history_title)).performScrollTo().performClick()
        compose.waitUntil(5_000) { compose.onAllNodes(hasTestTag("budget-history-read-source"))
            .fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("budget-history-read-source").performScrollTo().assertIsDisplayed()
    }

    private fun showPlans() {
        compose.setContent {
            if (mounted.value) CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Default) {
                    MainNavGraph(MainNavigationRuntime(rememberNavController(), harness.shell, currentFactory()),
                        remember { SnackbarHostState() },
                        SettingsPreferenceControls(AppSkin.Default, AppThemeMode.System, CurrencyCode.CNY,
                            onThemeModeChange = {}, onCurrencyChange = {}),
                        onBindingCleared = { error("Reading must preserve the binding") })
                }
            }
        }
        compose.waitForIdle()
        compose.runOnIdle { harness.shell.selectPrimaryDomain(PrimaryDomain.Plans.key) }
        compose.waitForIdle()
    }

    private fun currentFactory(): MainScreenFactory {
        val graph = harness.fixture.graph
        return MainScreenFactory(harness.screenFactory.repositories.copy(
            repository = graph.expenseRepository, uploadIntents = harness.fixture.uploadIntents,
            ledgerRepository = graph.ledgerRepository, recurringRepository = graph.recurringRepository,
            budgetRepository = graph.budgetRepository, reportsRepository = graph.reportsRepository,
            goalEditRepository = graph.goalEditRepository, ruleRepository = graph.ruleRepository,
            incomePlanRepository = graph.incomePlanRepository, debtRepository = graph.debtRepository,
            debtCreationRepository = graph.debtCreationRepository, debtWriteRepository = graph.debtWriteRepository,
            repaymentDraftRepository = graph.repaymentDraftRepository, outboxRepository = harness.fixture.outbox,
            tagRepository = graph.tagRepository, categoryPreferenceRepository = graph.categoryPreferenceRepository,
            ledgerCalendarRepository = harness.fixture.ledgerCalendarRepository,
        ), harness.screenFactory.viewModelFactories)
    }

    private fun sourceText(tag: String = "budget-read-source"): String = compose.onAllNodes(
        hasTestTag(tag) or hasAnyAncestor(hasTestTag(tag)), useUnmergedTree = true,
    ).fetchSemanticsNodes().flatMap { it.config.getOrNull(SemanticsProperties.Text).orEmpty() }
        .joinToString(" ") { it.text }

    private fun readTime(tag: String = "budget-read-source"): String? = Regex("\\d{4}年\\d{1,2}月\\d{1,2}日 \\d{2}:\\d{2}")
        .find(sourceText(tag))?.value

    private fun waitForAmount() = compose.waitUntil(5_000) {
        compose.onAllNodes(hasText("¥789")).fetchSemanticsNodes().isNotEmpty()
    }
}

internal class OfflineBudgetTransport {
    lateinit var service: ApiService
        private set
    val reads = CopyOnWriteArrayList<String>()
    val readScopes = CopyOnWriteArrayList<Pair<String, String?>>()
    @Volatile var offline = false
    @Volatile var denied = false
    @Volatile var beforeNextRead: (suspend () -> Unit)? = null
    var uiMonth: String? = null
    var original = offlineBudget()

    fun wrap(delegate: ApiService): ApiService = object : ApiService by delegate {
        override suspend fun budgetHistory(month: String, beforeVersion: Long?): com.ticketbox.data.remote.dto.BudgetHistoryDto {
            if (denied) throw HttpException(Response.error<Any>(403, "{}".toResponseBody()))
            if (offline) throw ConnectException("Synthetic unavailable budget history transport")
            return budgetHistoryPage(month, beforeVersion)
        }
        override suspend fun months(timezone: String?) = MonthsDto(listOf(uiMonth ?: original.month))
        override suspend fun monthlyStats(month: String?, tag: String?, timezone: String?, homeCurrencyCode: String?) =
            delegate.monthlyStats(month, tag, timezone, homeCurrencyCode).copy(month = month ?: uiMonth ?: original.month)
        override suspend fun dashboardCards(surface: String) = DashboardCardsResponseDto(surface,
            listOf(DashboardCardDto(DASHBOARD_CARD_BUDGET, "预算", true, 0)))
        override suspend fun runtimeCompatibility() = delegate.runtimeCompatibility().let {
            it.copy(capabilities = it.capabilities.copy(accountingTimeInputVersion = 1))
        }
        override suspend fun ledgerCalendar(ledgerId: String, revision: Long?) =
            LedgerCalendarDto(ledgerId, 1, "Asia/Shanghai", "explicit", "2026-09-01T00:00:00Z")
        override suspend fun monthlyBudget(month: String, timezone: String?): BudgetMonthlyDto {
            reads += month
            readScopes += month to timezone
            val captured = original.copy(month = month)
            beforeNextRead?.let { beforeNextRead = null; it(); return captured }
            if (denied) throw HttpException(Response.error<Any>(403, "{}".toResponseBody()))
            if (offline) throw ConnectException("Synthetic unavailable budget transport")
            return captured
        }
    }.also { service = it }
}

internal fun offlineBudget() = BudgetMonthlyDto(
    ledgerId = "correction-ledger", month = "2026-09", configured = true, homeCurrencyCode = "JPY", rowVersion = 7,
    totalAmountCents = 1200, rolloverAmountCents = 0, fixedAmountCents = 0, nonMonthlyAmountCents = 0,
    flexBudgetCents = 1200, spentAmountCents = 411, excludedAmountCents = 0, remainingAmountCents = 789,
    overspentAmountCents = 0, excludedCategories = listOf("医疗"), excludedBreakdown = emptyList(),
    categoryBudgets = listOf(BudgetCategoryDto("餐饮", 500, null, null, null)), updatedAt = "2026-09-01T00:00:00Z",
)

package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToIndex
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.NavHostController
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.closeSoftKeyboard
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.IncomePlanListResponseDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.theme.TicketboxTheme
import java.time.YearMonth
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Production navigation and expense confirmation; only server responses are controlled. */
class PlanningFinancialRefreshRouteTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val transport = PlanningBudgetTransport()
    private val harness = FactEntryNavigationHarness(context, transport::wrap)
    private val mounted = mutableStateOf(true)
    private lateinit var outer: NavHostController

    init {
        harness.fixture.network.current = harness.fixture.network.current.copy(
            status = "pending", confirmedAt = null, homeCurrencyCode = "JPY", amountCents = 400,
        )
        transport.hasConfirmedExpense = { harness.fixture.network.current.status == "confirmed" }
    }

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun confirmingAnExpenseRefreshesTheRetainedPlanOverviewWithoutPullToRefresh() {
        showPlans()
        waitForText("¥2,400")
        compose.onNodeWithText("¥2,400").assertIsDisplayed()
        val readsBeforeLeaving = transport.reads.size

        confirmExpenseFromInbox()
        switchDomain(PrimaryDomain.Plans)

        waitForText("¥2,000")
        compose.onNodeWithText("¥2,000").assertIsDisplayed()
        assertTrue("Returning must query the changed financial facts", transport.reads.size > readsBeforeLeaving)
        assertEquals(MainProductDestination.Domain(PrimaryDomain.Plans), harness.shell.activeDestination)
        assertTrue(harness.fixture.stored().isEmpty())
    }

    @Test fun restoredBudgetPageRefreshesItsSummaryAndKeepsTheOriginalDraftCurrencyAndOcc() {
        showPlans()
        waitForText("¥2,400")
        compose.runOnIdle { harness.shell.openSecondaryPage(ProductSecondaryPage.Budget) }
        waitForText(context.getString(R.string.budget_editor_total_label))
        val field = compose.onNode(hasSetTextAction() and hasAnyAncestor(hasTestTag("budget_total_amount")),
            useUnmergedTree = true)
        field.performScrollTo().performTextReplacement("3000.00")
        closeSoftKeyboard()
        field.assertTextEquals("3000.00")

        // Another client changes the budget while this device retains its original edit basis.
        transport.budgetEditedElsewhere = true
        confirmExpenseFromInbox()
        switchDomain(PrimaryDomain.Plans)

        compose.onNode(hasScrollToIndexAction()).performScrollToIndex(0)
        waitForText("¥4,400")
        compose.onNodeWithText("¥4,400").performScrollTo().assertIsDisplayed()
        field.performScrollTo().assertTextEquals("3000.00")
        compose.onNodeWithText(context.getString(R.string.budget_editor_save)).performScrollTo().performClick()
        compose.waitUntil(5_000) { runBlocking { harness.fixture.pendingDao.allRows().size == 1 } }
        val row = runBlocking { harness.fixture.pendingDao.allRows().single() }
        val original = requireNotNull(OutboxAdapterGraph().budgetSaveAdapter.fromJson(row.payload))
        assertEquals(PendingMutationType.SaveMonthlyBudget.wireValue, row.type)
        assertEquals(1L, row.expectedRowVersion)
        assertEquals("JPY", original.request.homeCurrencyCode)
        assertEquals(3000L, original.request.totalAmountCents)
        assertEquals(transport.reads.first(), original.month)
        assertTrue(!row.idempotencyKey.isNullOrBlank())
    }

    private fun showPlans() {
        compose.setContent {
            if (mounted.value) CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Paper) {
                    outer = rememberNavController()
                    MainNavGraph(
                        MainNavigationRuntime(outer, harness.shell, harness.screenFactory),
                        remember { SnackbarHostState() },
                        SettingsPreferenceControls(AppSkin.Paper, AppThemeMode.System, CurrencyCode.CNY,
                            onThemeModeChange = {}, onCurrencyChange = {}),
                        onBindingCleared = { error("Financial refresh must preserve the binding") },
                    )
                }
            }
        }
        compose.waitForIdle()
        switchDomain(PrimaryDomain.Plans)
    }

    private fun switchDomain(domain: PrimaryDomain) {
        compose.runOnIdle { harness.shell.selectPrimaryDomain(domain.key) }
        compose.waitForIdle()
    }

    private fun confirmExpenseFromInbox() {
        switchDomain(PrimaryDomain.Inbox)
        compose.runOnIdle { outer.openExpense(42L) }
        val confirm = context.getString(R.string.expense_edit_confirm_button)
        waitForText(confirm)
        compose.onNodeWithText(confirm).performScrollTo().performClick()
        compose.waitUntil(5_000) { harness.fixture.network.current.status == "confirmed" &&
            outer.currentBackStackEntry?.destination?.route == MAIN_ROUTE }
        compose.waitForIdle()
        assertEquals(listOf("save", "confirm"), harness.fixture.network.editCalls)
    }

    private fun waitForText(text: String) {
        compose.waitUntil(5_000) { compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty() }
    }
}

private class PlanningBudgetTransport {
    val reads = CopyOnWriteArrayList<String>()
    var hasConfirmedExpense: () -> Boolean = { false }
    var budgetEditedElsewhere = false

    fun wrap(delegate: ApiService): ApiService = object : ApiService by delegate {
        override suspend fun monthlyBudget(month: String, timezone: String?): BudgetMonthlyDto {
            reads += month
            val total = if (budgetEditedElsewhere) 4800L else 2400L
            val spent = if (hasConfirmedExpense()) 400L else 0L
            return BudgetMonthlyDto(ledgerId = "correction-ledger", month = month, configured = true,
                totalAmountCents = total, rolloverAmountCents = 0, fixedAmountCents = 0, nonMonthlyAmountCents = 0,
                flexBudgetCents = total, spentAmountCents = spent, excludedAmountCents = 0,
                remainingAmountCents = total - spent, overspentAmountCents = 0, excludedCategories = emptyList(),
                excludedBreakdown = emptyList(), categoryBudgets = emptyList(), updatedAt = "2026-09-12T00:00:00Z",
                rowVersion = if (budgetEditedElsewhere) 2 else 1, homeCurrencyCode = "JPY")
        }

        override suspend fun listIncomePlans(status: String) = IncomePlanListResponseDto(
            emptyList(), 0, YearMonth.now().toString(), 0, 0, 0, "JPY")
    }
}

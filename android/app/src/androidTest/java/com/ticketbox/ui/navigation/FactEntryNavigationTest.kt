package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.NavHostController
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.theme.TicketboxTheme
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** The outer and inner controllers, route callbacks and detail factories are all production code. */
class FactEntryNavigationTest {
    @JvmField
    @Rule
    val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val harness = FactEntryNavigationHarness(context)
    private val mounted = mutableStateOf(true)
    private lateinit var outer: NavHostController

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun workspaceRecoveryOpensTheRealFactAndReturnsToItsOriginalSubmission() {
        val original = runBlocking { harness.saveFailedCorrection() }
        installMainGraph()
        compose.runOnIdle { harness.shell.openAccount() }
        val entry = context.getString(R.string.settings_root_entry_offline_sync_title)
        waitForText(entry)
        compose.onNodeWithText(entry)
            .performScrollTo().performClick()
        openRecoveryFactAndReturn()
        assertEquals(original, harness.fixture.stored().single())
        assertEquals(MainProductDestination.Workspace, harness.shell.activeDestination)
    }

    @Test fun obligationRecoveryOpensTheRealFactAndReturnsToItsOriginalSubmission() {
        val original = runBlocking { harness.saveFailedCorrection() }
        installMainGraph()
        compose.runOnIdle { harness.shell.openSecondaryPage(ProductSecondaryPage.ObligationSync) }
        openRecoveryFactAndReturn()
        assertEquals(original, harness.fixture.stored().single())
        assertEquals(MainProductDestination.Secondary(ProductSecondaryPage.ObligationSync), harness.shell.activeDestination)
    }

    @Test fun recurringPaymentOpensItsExactFactAndReturnsToTheRecurringList() {
        installMainGraph()
        compose.runOnIdle { harness.shell.openSecondaryPage(ProductSecondaryPage.Recurring) }
        waitForText(context.getString(R.string.recurring_hero_meta, 1))
        val openOccurrence = context.getString(R.string.occurrence_open)
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(openOccurrence))
        compose.onNodeWithText("家庭固定支出").assertIsDisplayed()
        compose.onNodeWithText(openOccurrence).performClick()
        val openPayment = context.getString(R.string.occurrence_open_payment)
        waitForText(openPayment)
        compose.onNodeWithText(openPayment).performScrollTo().performClick()
        assertRealFactAndReturn()
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(openOccurrence))
        compose.onNodeWithText("家庭固定支出").assertIsDisplayed()
        compose.onNodeWithText(openOccurrence).assertIsDisplayed()
        assertEquals(MainProductDestination.Secondary(ProductSecondaryPage.Recurring), harness.shell.activeDestination)
        assertEquals("navigation-recurring", harness.fixture.network.occurrenceReads.single().first)
        assertTrue(harness.fixture.stored().isEmpty())
    }

    private fun openRecoveryFactAndReturn() {
        waitForText("原因：导航核对原提交")
        compose.onNodeWithText("原因：导航核对原提交").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("刷新并核对当前事实").performScrollTo().performClick()
        assertRealFactAndReturn()
        compose.onNodeWithText(context.getString(R.string.sync_status_page_title)).performScrollTo().assertIsDisplayed()
        waitForText("原因：导航核对原提交")
        compose.onNodeWithText("原因：导航核对原提交").performScrollTo().assertIsDisplayed()
    }

    private fun assertRealFactAndReturn() {
        waitForText(context.getString(R.string.expense_fact_title))
        compose.onNodeWithText(context.getString(R.string.expense_fact_title)).assertIsDisplayed()
        waitForText("更正这笔账单")
        compose.onNodeWithText("更正这笔账单").performScrollTo().assertIsDisplayed()
        compose.runOnIdle {
            assertEquals(EXPENSE_ROUTE, outer.currentBackStackEntry?.destination?.route)
            assertEquals(42L, outer.currentBackStackEntry?.arguments?.getLong(EXPENSE_ID_ARG))
            assertTrue(harness.fixture.network.expenseReads.contains(42L))
            assertTrue(harness.fixture.network.calls.isEmpty())
        }
        // ExpenseFactScreen supplies backText="" to the production AppBackButton's semantics.
        compose.onNode(hasContentDescription("") and hasClickAction()).performScrollTo().performClick()
        compose.waitForIdle()
        compose.runOnIdle { assertEquals(MAIN_ROUTE, outer.currentBackStackEntry?.destination?.route) }
    }

    private fun waitForText(text: String) {
        compose.waitUntil(timeoutMillis = 5_000) {
            compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty()
        }
    }

    private fun installMainGraph() {
        compose.setContent {
            if (mounted.value) {
                CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                    TicketboxTheme(skin = AppSkin.Paper) {
                        val controller = rememberNavController()
                        outer = controller
                        MainNavGraph(
                            MainNavigationRuntime(controller, harness.shell, harness.screenFactory),
                            remember { SnackbarHostState() },
                            SettingsPreferenceControls(AppSkin.Paper, AppThemeMode.System, CurrencyCode.CNY,
                                onThemeModeChange = { error("Navigation must not change appearance") },
                                onCurrencyChange = { error("Navigation must not change currency") }),
                            onBindingCleared = { error("Navigation must preserve its binding") },
                        )
                    }
                }
            }
        }
        compose.waitForIdle()
        compose.runOnIdle { assertEquals(MAIN_ROUTE, outer.currentBackStackEntry?.destination?.route) }
    }
}

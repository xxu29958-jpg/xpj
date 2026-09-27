package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.R
import com.ticketbox.data.repository.IncomePlanConnectedFixture
import com.ticketbox.data.repository.IncomePlanPatch
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.IncomePlanEditViewModel
import com.ticketbox.viewmodel.incomePlanEditViewModelFactory
import kotlinx.coroutines.CompletableDeferred
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Real outer MAIN_ROUTE and inner production plan routes; pop destroys the income entry. */
class IncomePlanDraftNavigationRoomTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val base = FactEntryNavigationHarness(context)
    private val income = IncomePlanConnectedFixture(context)
    private val graph = income.reopen()
    private val acknowledge = CompletableDeferred<Unit>()
    private val repository = object : IncomePlanActions by graph.incomePlanRepository {
        override suspend fun enqueueUpdate(expectedBinding: LogicalSessionBinding, baseline: IncomePlan,
            patch: IncomePlanPatch, currency: CurrencyCode): Result<Long> {
            val result = graph.incomePlanRepository.enqueueUpdate(expectedBinding, baseline, patch, currency)
            if (result.isSuccess) acknowledge.await()
            return result
        }
    }
    private val factory = MainScreenFactory(base.screenFactory.repositories.copy(
        incomePlanRepository = repository, outboxRepository = income.outbox,
    ), base.screenFactory.viewModelFactories)
    private val mounted = mutableStateOf(true)
    private lateinit var outer: NavHostController
    private lateinit var inner: NavHostController

    @After fun close() {
        acknowledge.complete(Unit)
        compose.runOnIdle { mounted.value = false; base.models.viewModelStore.clear() }
        compose.waitForIdle()
        income.close()
        base.close()
    }

    @Test fun actualPopAndReentryKeepTheOriginalRawDraftAndItsInFlightAcceptance() {
        showRoutes()
        enterIncome()
        compose.onNodeWithText("九月工资计划").performScrollTo().performClick()
        compose.onNodeWithText("100.00").performScrollTo().performTextReplacement("00120.00")
        val originalEditor = retainedEditor()
        val original = requireNotNull(originalEditor.state.value.session)
        val originalEntry = compose.runOnIdle { requireNotNull(inner.currentBackStackEntry) }
        compose.runOnIdle { assertTrue(inner.popBackStack()) }
        compose.waitUntil(10_000) { originalEntry.lifecycle.currentState == Lifecycle.State.DESTROYED }
        assertEquals(original, originalEditor.state.value.session)
        assertTrue(income.stored().isEmpty())
        enterIncome()
        assertNotSame(originalEntry, compose.runOnIdle { inner.currentBackStackEntry })
        assertSame(originalEditor, retainedEditor())
        assertEquals(original, retainedEditor().state.value.session)
        compose.onNodeWithText("00120.00").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("保存").performScrollTo().performClick()
        compose.waitUntil(10_000) { income.stored().size == 1 && originalEditor.state.value.isSubmitting }
        val accepted = income.stored().single()
        compose.runOnIdle { assertTrue(inner.popBackStack()) }
        compose.waitUntil(10_000) { inner.currentBackStackEntry?.destination?.route == PrimaryDomain.Plans.route }
        enterIncome()
        assertSame(originalEditor, retainedEditor())
        assertTrue(originalEditor.state.value.isSubmitting)
        compose.onNodeWithText(context.getString(R.string.income_plan_sheet_submitting)).performScrollTo().assertIsNotEnabled()
        acknowledge.complete(Unit)
        compose.waitUntil(10_000) { originalEditor.state.value.session == null && !originalEditor.state.value.isSubmitting }
        assertEquals(1, income.stored().size)
        for (key in listOf("payload", "expectedRowVersion", "idempotencyKey", "ownerKey", "ledgerId")) {
            assertEquals(accepted[key], income.stored().single()[key])
        }
        assertTrue(income.network.calls.isEmpty())
    }

    private fun showRoutes() {
        compose.setContent {
            if (mounted.value) CompositionLocalProvider(LocalViewModelStoreOwner provides base.models) {
                TicketboxTheme(skin = AppSkin.Paper) {
                    outer = rememberNavController()
                    NavHost(outer, startDestination = MAIN_ROUTE) {
                        composable(MAIN_ROUTE) {
                            inner = rememberNavController()
                            NavHost(inner, startDestination = PrimaryDomain.Plans.route) {
                                composable(PrimaryDomain.Plans.route) { }
                                addPlanRoutes(MainProductRouteDependencies(
                                    MainNavigationRuntime(outer, base.shell, factory), inner,
                                    MainWorkspaceControls(SettingsPreferenceControls(AppSkin.Paper, AppThemeMode.System,
                                        CurrencyCode.CNY, onThemeModeChange = {}, onCurrencyChange = {}),
                                        onBindingCleared = { error("Navigation preserves the identity") }),
                                ))
                            }
                        }
                    }
                }
            }
        }
        compose.waitForIdle()
    }

    private fun enterIncome() {
        compose.runOnIdle { inner.navigate(ProductSecondaryPage.IncomePlans.route) }
        compose.waitUntil(10_000) { compose.onAllNodesWithText("九月工资计划").fetchSemanticsNodes().isNotEmpty() }
        compose.waitForIdle()
    }

    private fun retainedEditor(): IncomePlanEditViewModel = compose.runOnIdle {
        ViewModelProvider(outer.getBackStackEntry(MAIN_ROUTE), incomePlanEditViewModelFactory(repository))[
            IncomePlanEditViewModelKey, IncomePlanEditViewModel::class.java]
    }
}

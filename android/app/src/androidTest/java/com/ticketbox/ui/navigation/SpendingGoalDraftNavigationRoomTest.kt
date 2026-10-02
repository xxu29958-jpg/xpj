package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.semantics.SemanticsProperties
import com.ticketbox.ui.assertEditableTextEquals
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.junit4.v2.createComposeRule
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
import androidx.test.espresso.Espresso.closeSoftKeyboard
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.CreateSpendingGoalViewModel
import com.ticketbox.viewmodel.createSpendingGoalViewModelFactory
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotSame
import org.junit.Assert.assertSame
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** The production plan route is destroyed; the original creation belongs to MAIN_ROUTE. */
class SpendingGoalDraftNavigationRoomTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val harness = FactEntryNavigationHarness(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun goals(month: String?, includeArchived: Boolean, goalType: String?, timezone: String?) =
                GoalListResponseDto(emptyList())
            override suspend fun runtimeCompatibility() = delegate.runtimeCompatibility().let { runtime ->
                runtime.copy(capabilities = runtime.capabilities.copy(currency = runtime.capabilities.currency.copy(
                    homeCurrencyCode = "CNY", minorUnitExponent = 2, readCompatibility = "compatible")))
            }
        }
    }
    private val mounted = mutableStateOf(true)
    private lateinit var outer: NavHostController
    private lateinit var inner: NavHostController

    @After fun close() {
        try {
            compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
            compose.waitForIdle()
        } finally { harness.close() }
    }

    @Test fun realRouteReentryRetainsTheChosenMonthAndRawDraftUntilExplicitDiscard() {
        showRoutes()
        enterGoals()
        compose.onNodeWithText(context.getString(R.string.spending_goals_create_action)).performClick()
        val originalOwner = creationOwner()
        compose.waitUntil(10_000) { originalOwner.state.value.editable && originalOwner.state.value.ledgerCurrency == CurrencyCode.CNY }
        compose.onAllNodes(hasSetTextAction())[0].performScrollTo().performTextReplacement("  旅行原稿  ")
        compose.onAllNodes(hasSetTextAction())[1].performScrollTo().performTextReplacement("00120.00")
        compose.onAllNodes(hasSetTextAction())[2].performScrollTo().performTextReplacement("出行")
        closeSoftKeyboard()
        compose.waitForIdle()
        compose.onNodeWithText(context.getString(R.string.budget_month_next)).performScrollTo().performClick()
        val original = originalOwner.state.value
        val entry = compose.runOnIdle { requireNotNull(inner.currentBackStackEntry) }
        compose.runOnIdle { assertTrue(inner.popBackStack()) }
        compose.waitUntil(10_000) { entry.lifecycle.currentState == Lifecycle.State.DESTROYED }
        enterGoals()
        assertNotSame(entry, compose.runOnIdle { inner.currentBackStackEntry })
        assertSame(originalOwner, creationOwner())
        compose.onNodeWithText(context.getString(R.string.goal_draft_continue)).performClick()
        compose.onAllNodes(hasSetTextAction())[0].assertEditableTextEquals("  旅行原稿  ")
        compose.onAllNodes(hasSetTextAction())[1].assertEditableTextEquals("00120.00")
        compose.onAllNodes(hasSetTextAction())[2].assertEditableTextEquals("出行")
        assertEquals(original.month, originalOwner.state.value.month)
        assertEquals(original.ledgerCurrency, originalOwner.state.value.ledgerCurrency)
        assertEquals(original.creationKey, originalOwner.state.value.creationKey)
        assertTrue(harness.fixture.stored().isEmpty())
        compose.onNodeWithText(context.getString(R.string.goal_draft_discard)).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.common_cancel)).performClick()
        compose.onAllNodes(hasSetTextAction())[0].assertEditableTextEquals("  旅行原稿  ")
        compose.onNodeWithText(context.getString(R.string.goal_draft_discard)).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.goal_draft_discard_confirm)).performClick()
        compose.onNodeWithText(context.getString(R.string.spending_goals_create_action)).performClick()
        assertEquals("", compose.onAllNodes(hasSetTextAction())[0].fetchSemanticsNode().config[SemanticsProperties.EditableText].text)
        assertEquals("", compose.onAllNodes(hasSetTextAction())[1].fetchSemanticsNode().config[SemanticsProperties.EditableText].text)
        assertEquals("", compose.onAllNodes(hasSetTextAction())[2].fetchSemanticsNode().config[SemanticsProperties.EditableText].text)
        assertTrue(harness.fixture.stored().isEmpty())
    }

    private fun creationOwner(): CreateSpendingGoalViewModel = compose.runOnIdle {
        ViewModelProvider(outer.getBackStackEntry(MAIN_ROUTE),
            createSpendingGoalViewModelFactory(harness.screenFactory.goalEditRepository))[
            "create-spending-goal", CreateSpendingGoalViewModel::class.java]
    }

    private fun enterGoals() {
        compose.runOnIdle { inner.navigate(ProductSecondaryPage.SpendingGoal.route) }
        compose.waitForIdle()
    }

    private fun showRoutes() {
        compose.setContent {
            if (mounted.value) CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Paper) {
                    outer = rememberNavController()
                    NavHost(outer, startDestination = MAIN_ROUTE) {
                        composable(MAIN_ROUTE) {
                            inner = rememberNavController()
                            NavHost(inner, startDestination = PrimaryDomain.Plans.route) {
                                composable(PrimaryDomain.Plans.route) { }
                                addPlanRoutes(MainProductRouteDependencies(
                                    MainNavigationRuntime(outer, harness.shell, harness.screenFactory), inner,
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
}

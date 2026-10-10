package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.graphics.asAndroidBitmap
import com.ticketbox.ui.assertEditableTextEquals
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
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
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.CreateSpendingGoalViewModel
import com.ticketbox.viewmodel.createSpendingGoalViewModelFactory
import com.ticketbox.viewmodel.SpendingGoalsViewModel
import com.ticketbox.viewmodel.spendingGoalsViewModelFactory
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
    private var goal = GoalDto(
        publicId = "navigation-spending-goal", ledgerId = "correction-ledger", name = "餐饮控制",
        goalType = "spending_limit", period = "monthly", month = "2026-10", category = "餐饮",
        targetAmountCents = 90_000, spentAmountCents = 60_000, remainingAmountCents = 30_000,
        progressPercent = 67, progressState = "on_track", status = "active", rowVersion = 2,
        createdAt = "2026-09-01T00:00:00Z", updatedAt = "2026-09-02T00:00:00Z", archivedAt = null,
        homeCurrencyCode = "CNY",
    )
    private val harness = FactEntryNavigationHarness(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun goals(month: String?, includeArchived: Boolean, goalType: String?, timezone: String?): GoalListResponseDto {
                goal = goal.copy(month = month ?: goal.month)
                val active = listOf(goal, goal.copy(publicId = "navigation-jpy-goal",
                    name = "带家人出行的交通和日常餐饮完整目标名称", category = "旅行期间的交通与日常餐饮支出",
                    homeCurrencyCode = "JPY", targetAmountCents = 1200, spentAmountCents = null,
                    remainingAmountCents = null, progressPercent = null, progressState = "unavailable"),
                    goal.copy(publicId = "navigation-over-goal", name = "本月总额控制", category = null,
                        targetAmountCents = 500_000, spentAmountCents = 620_000, remainingAmountCents = -120_000,
                        progressPercent = 124, progressState = "over_limit"))
                return GoalListResponseDto(if (includeArchived) active + archivedGoal() else active)
            }
            override suspend fun goal(publicId: String, timezone: String?): GoalDto {
                check(publicId == goal.publicId || publicId == archivedGoal().publicId)
                return if (publicId == goal.publicId) goal else archivedGoal()
            }
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
        compose.onNodeWithText(goal.name).performScrollTo()
        capture("goal-list")
        compose.onNodeWithText("带家人出行的交通和日常餐饮完整目标名称").performScrollTo()
        capture("goal-unavailable")
        compose.onNodeWithText("本月总额控制").performScrollTo()
        capture("goal-over-limit")
        scrollToText(context.getString(R.string.spending_goals_archived_show))
        compose.onNodeWithText(context.getString(R.string.spending_goals_archived_show)).performClick()
        val list = listOwner()
        compose.waitUntil(10_000) { list.state.value.goals.any { it.publicId == archivedGoal().publicId } }
        scrollToText(archivedGoal().name)
        capture("goal-archived-list")
        compose.onNodeWithText(archivedGoal().name).performClick()
        compose.waitUntil(10_000) { compose.onAllNodesWithText(archivedGoal().name).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText(context.getString(R.string.spending_goal_edit_action)).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.spending_goal_archive_action)).assertDoesNotExist()
        capture("goal-archived-detail")
        scrollToText(context.getString(R.string.goal_history_title))
        compose.onNodeWithText(context.getString(R.string.goal_history_title)).assertExists()
        scrollToText(context.getString(R.string.spending_goal_detail_back))
        compose.onNodeWithText(context.getString(R.string.spending_goal_detail_back)).performClick()
        scrollToText(context.getString(R.string.spending_goals_archived_hide))
        compose.onNodeWithText(context.getString(R.string.spending_goals_archived_hide)).performClick()
        compose.waitUntil(10_000) { !list.state.value.isLoading && !list.state.value.includeArchived }
        compose.onNodeWithText(archivedGoal().name).assertDoesNotExist()
        scrollToText(goal.name)
        compose.onNodeWithText(goal.name).performClick()
        compose.waitUntil(10_000) { compose.onAllNodesWithText(context.getString(R.string.spending_goal_edit_action)).fetchSemanticsNodes().isNotEmpty() }
        capture("goal-detail")
        compose.onNodeWithText(context.getString(R.string.spending_goal_edit_action)).performClick()
        capture("goal-editor")
        compose.onNodeWithText(context.getString(R.string.spending_goal_edit_cancel)).performClick()
        scrollToText(context.getString(R.string.spending_goal_detail_back))
        compose.onNodeWithText(context.getString(R.string.spending_goal_detail_back)).performClick()
        compose.onNodeWithText(context.getString(R.string.spending_goals_create_action)).performClick()
        val originalOwner = creationOwner()
        compose.waitUntil(10_000) { originalOwner.state.value.editable && originalOwner.state.value.ledgerCurrency == CurrencyCode.CNY }
        capture("goal-create")
        scrollToText(context.getString(R.string.spending_goal_create_name_label))
        compose.onAllNodes(hasSetTextAction())[0].performScrollTo().performTextReplacement("  旅行原稿  ")
        compose.onAllNodes(hasSetTextAction())[1].performScrollTo().performTextReplacement("00120.00")
        compose.onAllNodes(hasSetTextAction())[2].performScrollTo().performTextReplacement("出行")
        closeSoftKeyboard()
        compose.waitForIdle()
        scrollToText(context.getString(R.string.budget_month_next))
        compose.onNodeWithText(context.getString(R.string.budget_month_next)).performClick()
        val original = originalOwner.state.value
        val entry = compose.runOnIdle { requireNotNull(inner.currentBackStackEntry) }
        compose.runOnIdle { assertTrue(inner.popBackStack()) }
        compose.waitUntil(10_000) { entry.lifecycle.currentState == Lifecycle.State.DESTROYED }
        enterGoals()
        assertNotSame(entry, compose.runOnIdle { inner.currentBackStackEntry })
        assertSame(originalOwner, creationOwner())
        compose.onNodeWithText(context.getString(R.string.goal_draft_continue)).performClick()
        scrollToText(context.getString(R.string.spending_goal_create_name_label))
        compose.onAllNodes(hasSetTextAction())[0].assertEditableTextEquals("  旅行原稿  ")
        compose.onAllNodes(hasSetTextAction())[1].assertEditableTextEquals("00120.00")
        compose.onAllNodes(hasSetTextAction())[2].assertEditableTextEquals("出行")
        assertEquals(original.month, originalOwner.state.value.month)
        assertEquals(original.ledgerCurrency, originalOwner.state.value.ledgerCurrency)
        assertEquals(original.creationKey, originalOwner.state.value.creationKey)
        closeSoftKeyboard()
        capture("goal-create-retained")
        assertTrue(harness.fixture.stored().isEmpty())
        scrollToText(context.getString(R.string.goal_draft_discard))
        compose.onNodeWithText(context.getString(R.string.goal_draft_discard)).performClick()
        compose.onNodeWithText(context.getString(R.string.common_cancel)).performClick()
        scrollToText(context.getString(R.string.spending_goal_create_name_label))
        compose.onAllNodes(hasSetTextAction())[0].assertEditableTextEquals("  旅行原稿  ")
        scrollToText(context.getString(R.string.goal_draft_discard))
        compose.onNodeWithText(context.getString(R.string.goal_draft_discard)).performClick()
        compose.onNodeWithText(context.getString(R.string.goal_draft_discard_confirm)).performClick()
        compose.onNodeWithText(context.getString(R.string.spending_goals_create_action)).performClick()
        scrollToText(context.getString(R.string.spending_goal_create_name_label))
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

    private fun archivedGoal() = goal.copy(publicId = "navigation-archived-goal", name = "已归档的旅行目标",
        status = "archived", progressState = "archived", archivedAt = "2026-10-01T00:00:00Z")

    private fun enterGoals() {
        compose.runOnIdle { inner.navigate(ProductSecondaryPage.SpendingGoal.route) }
        val list = listOwner()
        compose.waitUntil(10_000) { !list.state.value.isLoading && list.state.value.goals.any { it.publicId == goal.publicId } }
        scrollToText(goal.name)
    }

    private fun listOwner(): SpendingGoalsViewModel = compose.runOnIdle {
        ViewModelProvider(requireNotNull(inner.currentBackStackEntry), spendingGoalsViewModelFactory(
            harness.screenFactory.reportsRepository, harness.screenFactory.goalEditRepository,
            harness.screenFactory.repositories.ledgerCalendarRepository))[
            "spending-goals", SpendingGoalsViewModel::class.java]
    }

    private fun capture(name: String) {
        compose.waitForIdle()
        com.ticketbox.ui.saveConsumerArtPreview(name, compose.onRoot().captureToImage().asAndroidBitmap())
    }

    private fun scrollToText(text: String) {
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(text))
    }

    private fun showRoutes() {
        val skin = if (InstrumentationRegistry.getArguments().getString("captureSkin") == "midnight")
            AppSkin.Midnight else AppSkin.Paper
        compose.setContent {
            if (mounted.value) CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = skin) {
                    outer = rememberNavController()
                    NavHost(outer, startDestination = MAIN_ROUTE) {
                        composable(MAIN_ROUTE) {
                            inner = rememberNavController()
                            NavHost(inner, startDestination = PrimaryDomain.Plans.route) {
                                composable(PrimaryDomain.Plans.route) { }
                                addPlanRoutes(MainProductRouteDependencies(
                                    MainNavigationRuntime(outer, harness.shell, harness.screenFactory), inner,
                                    MainWorkspaceControls(SettingsPreferenceControls(skin, AppThemeMode.System,
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

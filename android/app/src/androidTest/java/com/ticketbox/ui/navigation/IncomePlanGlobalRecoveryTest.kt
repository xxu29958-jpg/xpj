package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isDialog
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.R
import com.ticketbox.data.repository.IncomePlanDraft
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.IncomeSourceType
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.screens.settings.SyncStatusNavigation
import com.ticketbox.ui.screens.settings.SyncStatusScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.IncomePlanViewModel
import com.ticketbox.viewmodel.OutboxRecoveryRepositories
import com.ticketbox.viewmodel.OutboxStatusViewModel
import com.ticketbox.viewmodel.incomePlanViewModelFactory
import com.ticketbox.viewmodel.outboxStatusViewModelFactory
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/** The original comes from the real owner and Room; global recovery opens the production income route. */
class IncomePlanGlobalRecoveryTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val harness = FactEntryNavigationHarness(context)
    private val mounted = mutableStateOf(true)
    private lateinit var navigation: NavHostController

    @Test fun legacyCompletionRemainsVisibleInBothEntrancesUntilLocalRecordIsRemoved() {
        val original = createFailedIncome()
        runBlocking { harness.fixture.outbox.markDone(requireNotNull(original["id"]).toLong()) }
        val completed = harness.fixture.stored().single()
        installGraph()
        val review = context.getString(R.string.income_plan_submission_review)
        waitForText(review)
        compose.onNodeWithText(context.getString(R.string.sync_status_overview_caption_review_required, 1)).assertIsDisplayed()
        // Open the ordinary income page without a selected original: unknown Done must not disappear.
        compose.runOnIdle { navigation.navigate(ProductSecondaryPage.IncomePlans.route) }
        waitForText(review)
        compose.onNodeWithText(context.getString(R.string.income_plan_submission_done)).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.income_plan_edit_retry)).assertDoesNotExist()
        val stop = context.getString(R.string.income_plan_submission_stop_record)
        compose.onNodeWithText(stop).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.income_plan_submission_stop_record_explanation)).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.common_cancel)).performClick()
        assertEquals(completed, harness.fixture.stored().single())
        compose.onNodeWithText(stop).performScrollTo().performClick()
        compose.onNode(hasText(stop) and hasClickAction() and hasAnyAncestor(isDialog())).performClick()
        compose.waitUntil(5_000) { harness.fixture.stored().isEmpty() }
    }

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun originalYenCreationStaysYenAndOpensTheExactIncomeSubmission() {
        val original = createFailedIncome()
        installGraph()
        val open = context.getString(R.string.income_plan_submission_open)
        waitForText(open)
        compose.onNodeWithText("JPY", substring = true).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("¥12.00", substring = true).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.income_plan_submission_details)).performScrollTo().performClick()
        compose.onNodeWithText(requireNotNull(original["idempotencyKey"]), substring = true).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.sync_status_failed_button_drop)).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.income_plan_edit_drop_explanation)).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.common_cancel)).performClick()
        assertEquals(original, harness.fixture.stored().single())
        compose.onNodeWithText(open).performScrollTo().performClick()
        waitForText("原日元收入 · 2026-09")
        compose.runOnIdle {
            assertEquals(requireNotNull(original["id"]).toLong(), routeModel().state.value.selectedSubmissionId)
            assertEquals(original["id"], navigation.currentBackStackEntry?.arguments?.getString("submission"))
        }
        assertEquals(original, harness.fixture.stored().single())
    }

    @Test fun missingOriginalIdDoesNotSelectAnotherSavedIncomeCreation() {
        val original = createFailedIncome()
        val missingId = requireNotNull(original["id"]).toLong() + 1000
        installGraph()
        compose.runOnIdle { navigation.navigate(incomePlanSubmissionRoute(missingId)) }
        val unavailable = context.getString(R.string.income_plan_submission_unavailable)
        waitForText(unavailable)
        compose.onNodeWithText(unavailable).performScrollTo().assertIsDisplayed()
        compose.runOnIdle { assertEquals(missingId, routeModel().state.value.selectedSubmissionId) }
        assertEquals(original, harness.fixture.stored().single())
    }

    @Test fun replacingBindingClosesGlobalStopConfirmationWithoutDeletingTheOriginal() {
        val original = createFailedIncome()
        installGraph()
        val drop = context.getString(R.string.sync_status_failed_button_drop)
        waitForText(drop)
        compose.onNodeWithText(drop).performScrollTo().performClick()
        val explanation = context.getString(R.string.income_plan_edit_drop_explanation)
        compose.onNodeWithText(explanation).assertIsDisplayed()
        compose.runOnIdle { harness.fixture.switchLedger() }
        compose.waitUntil(5_000) { compose.onAllNodesWithText(explanation).fetchSemanticsNodes().isEmpty() }
        compose.onNodeWithText(explanation).assertDoesNotExist()
        assertEquals(original, harness.fixture.stored().single())
    }

    private fun createFailedIncome(): Map<String, String?> = runBlocking {
        val binding = requireNotNull(harness.screenFactory.repository.captureDeferredLedgerBinding())
        val id = harness.screenFactory.incomePlanRepository.create(binding, IncomePlanDraft("2026-09", "JPY",
            "原日元收入", IncomeSourceType.SALARY, amountCents = 1200, payDay = 12)).getOrThrow()
        harness.fixture.outbox.markFailed(id, "client_upgrade_required")
        harness.fixture.stored().single()
    }

    private fun installGraph() {
        compose.setContent {
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models,
                LocalCurrencyDisplay provides CurrencyDisplay(CurrencyCode.CNY)) {
                TicketboxTheme(skin = AppSkin.Default) {
                    if (mounted.value) {
                        navigation = rememberNavController()
                        NavHost(navigation, startDestination = "income-sync") {
                            composable("income-sync") {
                                val global: OutboxStatusViewModel = viewModel(factory = globalFactory())
                                SyncStatusScreen(global, {}, SyncStatusNavigation({}, {}, {}, {}, {}, {}, {},
                                    { id -> navigation.navigate(incomePlanSubmissionRoute(id)) }))
                            }
                            addPlanRoutes(MainProductRouteDependencies(
                                MainNavigationRuntime(navigation, harness.shell, harness.screenFactory), navigation,
                                MainWorkspaceControls(SettingsPreferenceControls(AppSkin.Default, AppThemeMode.System,
                                    CurrencyCode.CNY, {}, {}), {})))
                        }
                    }
                }
            }
        }
    }

    private fun globalFactory() = harness.screenFactory.let { factory -> outboxStatusViewModelFactory(
        factory.outboxRepository, factory.repository, OutboxRecoveryRepositories(factory.debtCreationRepository,
            factory.recurringRepository.occurrences, factory.incomePlanRepository, factory.debtAdjustmentRepository,
            factory.goalEditRepository, factory.budgetRepository, factory.recurringRepository, factory.ruleRepository)) }

    private fun routeModel(): IncomePlanViewModel = ViewModelProvider(requireNotNull(navigation.currentBackStackEntry),
        incomePlanViewModelFactory(harness.screenFactory.incomePlanRepository))[
        IncomePlanViewModelKey, IncomePlanViewModel::class.java]

    private fun waitForText(text: String) = compose.waitUntil(5_000) {
        compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty()
    }
}

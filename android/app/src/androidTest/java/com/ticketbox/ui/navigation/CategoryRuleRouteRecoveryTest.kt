package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.R
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.CategoryRulesViewModel
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Rule
import org.junit.Test

/** Real library route, ViewModel, command owner and Room; no copied screen-state wiring. */
class CategoryRuleRouteRecoveryTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val harness = FactEntryNavigationHarness(context)
    private val mounted = mutableStateOf(true)
    private lateinit var navigation: NavHostController

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun missingOriginalIdKeepsReviewEvenWhenAnotherOriginalExists() {
        val original = createFailedRule()
        val existingId = requireNotNull(original["id"]).toLong()
        val missingId = existingId + 1000
        openRuleSubmission(missingId)
        waitForText("原日元月票")
        val unavailable = context.getString(R.string.category_rule_submission_unavailable)
        waitForText(unavailable)
        compose.onNodeWithText(unavailable).performScrollTo().assertIsDisplayed()
        compose.runOnIdle {
            val state = routeModel().uiState.value
            assertEquals(missingId, state.selectedSubmissionId)
            assertEquals(listOf(existingId), state.pendingSubmissions.map { it.row.id })
            assertEquals(missingId.toString(), navigation.currentBackStackEntry?.arguments?.getString("submission"))
        }
        assertEquals(original, harness.fixture.stored().single())
    }

    @Test fun replacingBindingClosesTheOriginalStopDialogAndPreservesItsRoomRow() {
        val original = createFailedRule()
        val originalId = requireNotNull(original["id"]).toLong()
        openRuleSubmission(originalId)
        val stop = context.getString(R.string.category_rule_submission_stop)
        waitForText(stop)
        compose.onNodeWithText(stop).performScrollTo().performClick()
        val explanation = context.getString(R.string.category_rule_submission_stop_body)
        compose.onNodeWithText(explanation).assertIsDisplayed()
        val originalBinding = requireNotNull(harness.screenFactory.ruleRepository.currentAccess()).binding
        compose.runOnIdle { harness.fixture.switchLedger() }
        compose.waitUntil(5_000) {
            var currentBindingObserved = false
            compose.runOnIdle { currentBindingObserved = routeModel().uiState.value.binding?.ledgerId == "another-ledger" }
            currentBindingObserved && compose.onAllNodesWithText(explanation).fetchSemanticsNodes().isEmpty()
        }
        compose.onNodeWithText(explanation).assertDoesNotExist()
        compose.runOnIdle {
            assertNotEquals(originalBinding, harness.screenFactory.ruleRepository.currentAccess()?.binding)
            assertEquals("another-ledger", routeModel().uiState.value.binding?.ledgerId)
        }
        assertEquals(original, harness.fixture.stored().single())
    }

    private fun createFailedRule(): Map<String, String?> = runBlocking {
        val owner = harness.screenFactory.ruleRepository
        val id = owner.createCategoryRule(requireNotNull(owner.currentAccess()).binding,
            CategoryRuleRequest("原日元月票", "交通", true, 10, amountMinCents = 1200, homeCurrencyCode = "JPY")).getOrThrow()
        harness.fixture.outbox.markFailed(id, "client_upgrade_required")
        harness.fixture.stored().single()
    }

    private fun openRuleSubmission(id: Long) {
        compose.setContent {
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Default) {
                    if (mounted.value) {
                        navigation = rememberNavController()
                        NavHost(navigation, startDestination = TRANSACTIONS_LIBRARY_ROUTE) {
                            transactionsLibraryGraph(navigation, harness.screenFactory, {}, {}, {})
                        }
                    }
                }
            }
        }
        compose.runOnIdle { navigation.navigate(categoryRuleSubmissionRoute(id)) }
    }

    private fun routeModel(): CategoryRulesViewModel = ViewModelProvider(requireNotNull(navigation.currentBackStackEntry),
        harness.screenFactory.categoryRulesViewModelFactory)[transactionsLibraryViewModelKey("category-rules",
        harness.screenFactory.ledgerRepository.activeLedgerId()), CategoryRulesViewModel::class.java]

    private fun waitForText(text: String) = compose.waitUntil(5_000) {
        compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty()
    }
}

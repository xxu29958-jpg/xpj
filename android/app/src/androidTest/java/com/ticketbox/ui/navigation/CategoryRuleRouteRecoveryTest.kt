package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.closeSoftKeyboard
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.ui.saveConsumerArtPreview
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

    @Test fun unsentRuleKeepsItsOriginalFieldsWhenLeavingAndReopeningTheLibrary() {
        openRules()
        val add = context.getString(R.string.category_rule_editor_submit_create)
        waitForText(add)
        compose.onNodeWithText(add).performScrollTo().performClick()
        val raw = "  未完成的街角规则  "
        compose.onNode(hasSetTextAction() and hasText(context.getString(R.string.category_rule_editor_keyword_label)))
            .performScrollTo().performTextReplacement(raw)
        closeSoftKeyboard()
        compose.onNode(hasSetTextAction() and hasText(context.getString(R.string.category_rule_editor_category_label)))
            .performScrollTo().performTextReplacement("家庭餐饮")
        closeSoftKeyboard()
        compose.onNodeWithText(context.getString(R.string.category_rule_definition_conditions)).performScrollTo().performClick()
        compose.onNode(hasSetTextAction() and hasText(context.getString(R.string.category_rule_definition_source)))
            .performScrollTo().performTextReplacement("  支付宝原来源  ")
        closeSoftKeyboard()
        compose.onNode(hasSetTextAction() and hasText(context.getString(R.string.category_rule_definition_tag)))
            .performScrollTo().performTextReplacement("  家庭原标签  ")
        closeSoftKeyboard()
        val owner = harness.screenFactory.ruleRepository
        val binding = requireNotNull(owner.currentAccess()).binding
        val original = runBlocking { requireNotNull(owner.definitionInputs).read(binding).single() }
        InstrumentationRegistry.getInstrumentation().uiAutomation.waitForIdle(500, 5_000)
        compose.runOnIdle { navigation.popBackStack() }
        compose.waitForIdle()
        compose.runOnIdle { mounted.value = false }
        compose.waitForIdle()
        compose.runOnIdle { harness.reopen(); mounted.value = true }
        compose.waitForIdle()
        compose.runOnIdle { navigation.navigate(TRANSACTIONS_LIBRARY_RULES_ROUTE) }
        waitForText(add)
        compose.waitUntil(5_000) { routeModel().definitions.state.value.ready }
        compose.onNodeWithText(add).performScrollTo().performClick()
        compose.onNodeWithText(raw).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("家庭餐饮").assertIsDisplayed()
        saveConsumerArtPreview("rule-definition-retained-${visualMode()}",
            requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        compose.onNodeWithText("  支付宝原来源  ").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("  家庭原标签  ").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.category_rule_editor_cancel)).performScrollTo().assertIsDisplayed()
        saveConsumerArtPreview("rule-definition-actions-${visualMode()}",
            requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        assertEquals(original, runBlocking { requireNotNull(harness.screenFactory.ruleRepository.definitionInputs).read(binding).single() })
        assertEquals(emptyList<Map<String, String?>>(), harness.fixture.stored())
    }

    @Test fun viewerCanReadOriginalInputButCannotEditOrSubmitIt() {
        openRules()
        val add = context.getString(R.string.category_rule_editor_submit_create)
        waitForText(add)
        compose.onNodeWithText(add).performScrollTo().performClick()
        compose.onNode(hasSetTextAction() and hasText(context.getString(R.string.category_rule_editor_keyword_label)))
            .performTextReplacement("只读后仍保留的规则")
        closeSoftKeyboard()
        val owner = harness.screenFactory.ruleRepository
        val binding = requireNotNull(owner.currentAccess()).binding
        val original = runBlocking { requireNotNull(owner.definitionInputs).read(binding).single() }
        compose.runOnIdle { harness.fixture.role("viewer") }
        waitForText(context.getString(R.string.common_readonly_ledger))
        compose.onNodeWithText("只读后仍保留的规则").performScrollTo().assertIsDisplayed().assertIsNotEnabled()
        compose.onNodeWithText(add).performScrollTo().assertIsNotEnabled()
        compose.onNodeWithText(context.getString(R.string.category_rule_editor_cancel)).performScrollTo().performClick()
        compose.onNodeWithText(add).assertDoesNotExist()
        compose.onNodeWithText("只读后仍保留的规则").performScrollTo().performClick()
        compose.onNodeWithText("只读后仍保留的规则").performScrollTo().assertIsDisplayed().assertIsNotEnabled()
        assertEquals(original, runBlocking { requireNotNull(owner.definitionInputs).read(binding).single() })
        assertEquals(emptyList<Map<String, String?>>(), harness.fixture.stored())
        org.junit.Assert.assertTrue(runBlocking { owner.createCategoryRule(binding,
            CategoryRuleRequest("只读后仍保留的规则", "餐饮", true, 10), original).isFailure })
    }

    @Test fun renewedSessionNeedsExplicitIdentityReviewBeforeTheOriginalInputCanBeSubmitted() {
        openRules()
        val add = context.getString(R.string.category_rule_editor_submit_create)
        waitForText(add)
        compose.onNodeWithText(add).performScrollTo().performClick()
        compose.onNode(hasSetTextAction() and hasText(context.getString(R.string.category_rule_editor_keyword_label)))
            .performTextReplacement("重新登录后的原规则")
        closeSoftKeyboard()
        compose.onNode(hasSetTextAction() and hasText(context.getString(R.string.category_rule_editor_category_label)))
            .performTextReplacement("餐饮")
        closeSoftKeyboard()
        val owner = harness.screenFactory.ruleRepository
        val binding = requireNotNull(owner.currentAccess()).binding
        val original = runBlocking { requireNotNull(owner.definitionInputs).read(binding).single() }
        compose.runOnIdle { harness.fixture.renewBinding() }
        waitForText(context.getString(R.string.category_rule_draft_retained))
        compose.onNodeWithText("重新登录后的原规则").performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.category_rule_draft_binding_changed)).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(add).performScrollTo().assertIsNotEnabled()
        compose.onNodeWithText(context.getString(R.string.category_rule_draft_review_binding)).performScrollTo().performClick()
        compose.onNodeWithText("重新登录后的原规则").performScrollTo().assertIsEnabled()
        assertEquals(original.key, runBlocking { requireNotNull(owner.definitionInputs).read(binding).single().key })
        compose.onNodeWithText(add).performScrollTo().performClick()
        waitForText(context.getString(R.string.category_rule_submission_saved))
        assertEquals(original.key, harness.fixture.stored().single()["idempotencyKey"])
        org.junit.Assert.assertTrue(runBlocking { requireNotNull(owner.definitionInputs).read(binding).isEmpty() })
    }

    private fun createFailedRule(): Map<String, String?> = runBlocking {
        val owner = harness.screenFactory.ruleRepository
        val id = owner.createCategoryRule(requireNotNull(owner.currentAccess()).binding,
            CategoryRuleRequest("原日元月票", "交通", true, 10, amountMinCents = 1200, homeCurrencyCode = "JPY")).getOrThrow()
        harness.fixture.outbox.markFailed(id, "client_upgrade_required")
        harness.fixture.stored().single()
    }

    private fun openRuleSubmission(id: Long) = openRules(categoryRuleSubmissionRoute(id))

    private fun openRules(route: String = TRANSACTIONS_LIBRARY_RULES_ROUTE) {
        compose.setContent {
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = if (visualMode() == "large") AppSkin.Midnight else AppSkin.Paper) {
                    if (mounted.value) {
                        navigation = rememberNavController()
                        NavHost(navigation, startDestination = TRANSACTIONS_LIBRARY_ROUTE) {
                            transactionsLibraryGraph(navigation, harness.screenFactory, TransactionsLibraryWrites({}, {}, {}))
                        }
                    }
                }
            }
        }
        compose.runOnIdle { navigation.navigate(route) }
    }

    private fun routeModel(): CategoryRulesViewModel = ViewModelProvider(requireNotNull(navigation.currentBackStackEntry),
        harness.screenFactory.categoryRulesViewModelFactory)[transactionsLibraryViewModelKey("category-rules",
        harness.screenFactory.ledgerRepository.activeLedgerId()), CategoryRulesViewModel::class.java]

    private fun visualMode(): String = InstrumentationRegistry.getArguments().getString("visualMode") ?: "normal"

    private fun waitForText(text: String) = compose.waitUntil(5_000) {
        compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty()
    }
}

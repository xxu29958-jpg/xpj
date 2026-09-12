package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.junit4.StateRestorationTester
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.NavHostController
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.closeSoftKeyboard
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ConfirmedExpenseStreamItemDto
import com.ticketbox.data.remote.dto.ConfirmedStreamEntryKindDto
import com.ticketbox.data.remote.dto.ExpenseLineageStatusDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.domain.model.CurrencyDisplay
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Real navigation and Room commands; controlled responses keep obligation month separate from payment date. */
class RecurringPaymentJourneyRouteTest {
    @get:Rule val compose = createComposeRule()
    private val restoration = StateRestorationTester(compose)
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val transport = RecurringPaymentJourneyTransport()
    private val harness = FactEntryNavigationHarness(context, transport::wrap)
    private val mounted = mutableStateOf(true)
    private lateinit var outer: NavHostController

    init {
        transport.network = harness.fixture.network
        harness.fixture.network.confirmedStreamItems = { current ->
            if (transport.created && current.status == "confirmed") listOf(ConfirmedExpenseStreamItemDto(
                ConfirmedStreamEntryKindDto.Expense, requireNotNull(current.expenseTime).take(10), current.createdAt,
                current.id, requireNotNull(current.amountCents), current, lineageStatus = ExpenseLineageStatusDto.Confirmed,
                lineageHomeNetCents = requireNotNull(current.amountCents))) else emptyList()
        }
    }

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun newFixedCommitmentCapturesTheSelectedForeignCurrencyInItsOriginalCommand() {
        showRecurring()
        compose.onNodeWithText(context.getString(R.string.recurring_add_cta)).performScrollTo().performClick()
        waitForText(context.getString(R.string.recurring_form_amount_label))
        compose.onAllNodes(hasSetTextAction())[0].performTextReplacement("新增日元订阅")
        closeSoftKeyboard()

        // Current production renders this denomination as a label with no action.
        compose.onNode(hasText("${CurrencyCode.CNY.symbol} CNY") and hasClickAction())
            .performScrollTo().assertIsEnabled().performClick()
        compose.onNodeWithText("JPY").performClick()
        compose.onAllNodes(hasSetTextAction())[1].performTextReplacement("1200")
        closeSoftKeyboard()
        compose.onNodeWithText(context.getString(R.string.recurring_form_save)).performScrollTo().performClick()

        compose.waitUntil(5_000) { runBlocking { harness.fixture.pendingDao.allRows().size == 1 } }
        val row = runBlocking { harness.fixture.pendingDao.allRows().single() }
        val original = requireNotNull(OutboxAdapterGraph().recurringCreateAdapter.fromJson(row.payload))
        assertEquals(PendingMutationType.CreateRecurringItem.wireValue, row.type)
        assertEquals("correction-ledger", row.ledgerId)
        assertEquals("新增日元订阅", original.merchant)
        assertEquals("JPY", original.homeCurrencyCode)
        assertEquals(1200L, original.baselineAmountCents)
        assertEquals(0L, row.expectedRowVersion)
        assertFalse(row.idempotencyKey.isNullOrBlank())
        assertTrue(transport.linkCalls.isEmpty())
    }

    @Test fun missingPaymentStartsAPrefilledManualCommandWithoutFulfillingTheOriginalPeriod() {
        transport.recording = true
        showRecurring()
        openAugustOccurrence()
        compose.onNodeWithTag("occurrence-state").assertTextEquals(context.getString(R.string.occurrence_unfulfilled))
        waitForText(context.getString(R.string.occurrence_no_payments))

        // This missing entry is the product counterexample, not a future interface dependency.
        compose.onNodeWithText("记录本期付款").performScrollTo().assertIsEnabled().performClick()
        waitForText(context.getString(R.string.ledger_manual_sheet_title))
        val clientRef = compose.runOnIdle {
            requireNotNull(readRecurringPaymentOrigin(outer.currentBackStackEntry?.arguments?.getString("origin"))?.clientRef)
        }
        compose.onAllNodes(hasSetTextAction())[0].assertTextEquals("1200")
        compose.onAllNodes(hasSetTextAction())[1].assertTextEquals("日元订阅")
        compose.onAllNodes(hasSetTextAction())[2].performTextReplacement("购物")
        compose.onAllNodes(hasSetTextAction())[3].performTextReplacement("八月义务，九月付款")
        closeSoftKeyboard()
        restoration.emulateSavedInstanceStateRestore()
        waitForText(context.getString(R.string.ledger_manual_sheet_title))
        compose.onAllNodes(hasSetTextAction())[0].assertTextEquals("1200")
        compose.onAllNodes(hasSetTextAction())[1].assertTextEquals("日元订阅")
        compose.onAllNodes(hasSetTextAction())[2].assertTextEquals("购物")
        compose.onAllNodes(hasSetTextAction())[3].assertTextEquals("八月义务，九月付款")
        compose.onNodeWithText(context.getString(R.string.ledger_manual_pick_date_button))
            .performScrollTo().assertIsEnabled().performClick()
        waitForText(context.getString(R.string.ledger_manual_date_picker_title))
        compose.onNodeWithText(context.getString(R.string.common_cancel)).performClick()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()

        compose.waitUntil(5_000) { runBlocking { harness.fixture.pendingDao.allRows().size == 1 } }
        val row = runBlocking { harness.fixture.pendingDao.allRows().single() }
        val original = requireNotNull(OutboxAdapterGraph().manualCreateAdapter.fromJson(row.payload))
        assertEquals(PendingMutationType.CreateExpense.wireValue, row.type)
        assertEquals("correction-ledger", row.ledgerId)
        assertEquals("CNY", original.homeCurrencyCode)
        assertEquals("JPY", original.originalCurrency)
        assertEquals("1200", original.originalAmount)
        assertEquals("日元订阅", original.merchant)
        assertEquals("购物", original.category)
        assertEquals("八月义务，九月付款", original.note)
        assertEquals(clientRef, original.clientRef)
        assertFalse(original.spentAt.isNullOrBlank())
        assertTrue("Recording a payment must not submit a fulfillment", transport.linkCalls.isEmpty())
        assertEquals("2026-08", transport.reads.last().second)
        assertFalse(requireNotNull(original.spentAt).startsWith("2026-08"))
        completeAndAssociateOriginalPayment()
    }

    @Test fun loadedObligationCanCaptureItsOriginalPaymentAfterTheDeviceGoesOffline() {
        transport.ledgerHomeCurrencyCode = "USD"
        showRecurring()
        openAugustOccurrence()
        val originalReads = transport.preparationReads.toList()
        compose.runOnIdle { transport.offline = true }
        compose.onNodeWithText("记录本期付款").performScrollTo().assertIsEnabled().performClick()
        waitForText(context.getString(R.string.ledger_manual_sheet_title))
        val origin = compose.runOnIdle {
            requireNotNull(readRecurringPaymentOrigin(outer.currentBackStackEntry?.arguments?.getString("origin")))
        }
        compose.onAllNodes(hasSetTextAction())[0].assertTextEquals("1200")
        compose.onAllNodes(hasSetTextAction())[1].assertTextEquals("日元订阅")
        compose.onAllNodes(hasSetTextAction())[2].performTextReplacement("购物")
        closeSoftKeyboard()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        compose.waitUntil(5_000) { runBlocking { harness.fixture.pendingDao.allRows().size == 1 } }
        val row = runBlocking { harness.fixture.pendingDao.allRows().single() }
        val request = requireNotNull(OutboxAdapterGraph().manualCreateAdapter.fromJson(row.payload))
        assertEquals(PendingMutationType.CreateExpense.wireValue, row.type)
        assertEquals(origin.binding.ownerKey, row.ownerKey)
        assertEquals(origin.binding.ledgerId, row.ledgerId)
        assertEquals(origin.clientRef, request.clientRef)
        assertEquals("USD", request.homeCurrencyCode)
        assertEquals("JPY", request.originalCurrency)
        assertEquals("1200", request.originalAmount)
        assertEquals("日元订阅", request.merchant)
        assertEquals("购物", request.category)
        assertFalse(row.idempotencyKey.isNullOrBlank())
        assertEquals("2026-08", origin.period)
        assertEquals(originalReads, transport.preparationReads.toList())
        assertTrue(transport.linkCalls.isEmpty())
        val originalRows = harness.fixture.stored()
        restoration.emulateSavedInstanceStateRestore()
        waitForText(context.getString(R.string.manual_submission_title))
        assertEquals(originalRows, harness.fixture.stored())
    }

    private fun completeAndAssociateOriginalPayment() {
        waitForText(context.getString(R.string.manual_submission_title))
        val originalRows = harness.fixture.stored()
        restoration.emulateSavedInstanceStateRestore()
        waitForText(context.getString(R.string.manual_submission_title))
        assertEquals(originalRows, harness.fixture.stored())
        runBlocking { transport.drain(harness.fixture) }
        val open = context.getString(R.string.manual_submission_open)
        waitForText(open)
        compose.onNodeWithText(open).performScrollTo().performClick()
        waitForText(context.getString(R.string.expense_fx_refresh))
        assertTrue(transport.linkCalls.isEmpty())
        compose.runOnIdle { transport.completeFx() }
        compose.onNodeWithText(context.getString(R.string.expense_fx_refresh)).performScrollTo().performClick()
        val review = context.getString(R.string.expense_fx_load_review)
        waitForText(review)
        compose.onNodeWithText(review).performScrollTo().performClick()
        val confirm = context.getString(R.string.expense_edit_confirm_button)
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(confirm) and isEnabled()).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText(confirm).performScrollTo().performClick()
        waitForText(context.getString(R.string.occurrence_unfulfilled))
        compose.onNodeWithTag("occurrence-period").assertTextContains("2026-08")
        assertTrue(transport.linkCalls.isEmpty())
        compose.onNodeWithText(context.getString(R.string.occurrence_reserved, "JPY ${formatDisplayAmount(1200L, CurrencyDisplay(CurrencyCode.JPY))}"))
            .performScrollTo().assertIsDisplayed()
        val payment = "occurrence-payment-42"
        compose.waitUntil(5_000) { compose.onAllNodes(androidx.compose.ui.test.hasTestTag(payment)).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag(payment).performScrollTo().performClick()
        compose.onNodeWithTag("occurrence-submit").performScrollTo().performClick()
        compose.waitUntil(5_000) { runBlocking { harness.fixture.pendingDao.allRows().size == 2 } }
        assertTrue(transport.linkCalls.isEmpty())
        runBlocking { transport.drain(harness.fixture) }
        waitForText(context.getString(R.string.occurrence_fulfilled))
        assertEquals(1, transport.linkCalls.size)
        compose.onNodeWithText(context.getString(R.string.occurrence_reserved, "JPY ${formatDisplayAmount(0L, CurrencyDisplay(CurrencyCode.JPY))}"))
            .performScrollTo().assertIsDisplayed()
        assertEquals("2026-08", transport.reads.last().second)
    }

    @Test fun viewingTheLinkedPaymentReturnsToItsOriginalPeriodAndRefreshesThatPeriod() {
        transport.fulfilled = true
        showRecurring()
        openAugustOccurrence()
        compose.onNodeWithText(context.getString(R.string.occurrence_open_payment)).performScrollTo().performClick()
        waitForText(context.getString(R.string.expense_fact_title))
        compose.onNodeWithText(context.getString(R.string.expense_fact_title)).assertIsDisplayed()
        compose.runOnIdle {
            assertEquals(EXPENSE_ROUTE, outer.currentBackStackEntry?.destination?.route)
            assertEquals(42L, outer.currentBackStackEntry?.arguments?.getLong(EXPENSE_ID_ARG))
        }
        val priorReads = transport.reads.size
        compose.onNode(hasContentDescription("") and hasClickAction()).performScrollTo().performClick()
        compose.waitForIdle()

        // Current RecurringOccurrenceHost dismisses the session before opening the fact.
        compose.onNodeWithTag("occurrence-period").assertTextContains("2026-08")
        compose.waitUntil(5_000) { transport.reads.size > priorReads }
        assertEquals("navigation-recurring" to "2026-08", transport.reads.last())
        compose.onNodeWithTag("occurrence-state").assertTextEquals(context.getString(R.string.occurrence_fulfilled))
        assertTrue(transport.linkCalls.isEmpty())
        assertTrue(harness.fixture.stored().isEmpty())
        assertEquals(MainProductDestination.Secondary(ProductSecondaryPage.Recurring), harness.shell.activeDestination)
    }

    @Test fun legacyCommitmentWithoutCurrencyAllowsAnExplicitPaymentWithoutReinterpretingItsOldAmount() {
        transport.recordedCurrency = null
        showRecurring()
        openAugustOccurrence()
        compose.onNodeWithText("记录本期付款").performScrollTo().performClick()
        waitForText(context.getString(R.string.recurring_payment_currency_required))
        compose.onNodeWithText("JPY").performScrollTo().performClick()
        assertEquals("", compose.onAllNodes(hasSetTextAction())[0].fetchSemanticsNode()
            .config[SemanticsProperties.EditableText].text)
        compose.onAllNodes(hasSetTextAction())[1].assertTextEquals("日元订阅")
        compose.onAllNodes(hasSetTextAction())[0].performTextReplacement("1200")
        compose.onAllNodes(hasSetTextAction())[2].performTextReplacement("购物")
        closeSoftKeyboard()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        compose.waitUntil(5_000) { runBlocking { harness.fixture.pendingDao.allRows().size == 1 } }
        val row = runBlocking { harness.fixture.pendingDao.allRows().single() }
        val request = requireNotNull(OutboxAdapterGraph().manualCreateAdapter.fromJson(row.payload))
        assertEquals("JPY", request.originalCurrency)
        assertEquals("1200", request.originalAmount)
        assertEquals("CNY", request.homeCurrencyCode)
        assertTrue(transport.linkCalls.isEmpty())
    }

    private fun showRecurring() {
        restoration.setContent {
            if (mounted.value) CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Paper) {
                    outer = rememberNavController()
                    MainNavGraph(MainNavigationRuntime(outer, harness.shell, harness.screenFactory),
                        remember { SnackbarHostState() },
                        SettingsPreferenceControls(AppSkin.Paper, AppThemeMode.System, CurrencyCode.CNY,
                            onThemeModeChange = {}, onCurrencyChange = {}),
                        onBindingCleared = { error("Payment navigation must preserve the original binding") })
                }
            }
        }
        compose.waitForIdle()
        compose.runOnIdle { harness.shell.openSecondaryPage(ProductSecondaryPage.Recurring) }
        waitForText(context.getString(R.string.recurring_hero_meta, 1))
    }

    private fun openAugustOccurrence() {
        val open = context.getString(R.string.occurrence_open)
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(open))
        compose.onNodeWithText(open).performClick()
        waitForText(context.getString(if (transport.fulfilled) R.string.occurrence_fulfilled else R.string.occurrence_unfulfilled))
        compose.onNodeWithTag("occurrence-period").performTextReplacement("2026-08")
        closeSoftKeyboard()
        compose.onNodeWithText(context.getString(R.string.occurrence_show_period)).performClick()
        compose.waitUntil(5_000) { transport.reads.lastOrNull()?.second == "2026-08" }
        compose.waitUntil(5_000) {
            compose.onAllNodes(hasText(context.getString(R.string.occurrence_show_period)) and isEnabled())
                .fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithTag("occurrence-period").assertTextContains("2026-08")
    }

    private fun waitForText(text: String) {
        compose.waitUntil(5_000) { compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty() }
    }
}

package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.compose.rememberNavController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.NavType
import androidx.navigation.navArgument
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.closeSoftKeyboard
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtListResponseDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.repository.toEntity
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseDraft
import kotlinx.coroutines.flow.first
import org.junit.Rule
import org.junit.Test

/** Actual shortcut entry, form, ViewModel and Room admission, before the worker can send. */
class ManualCreationRouteRoomTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private var sends = 0
    private val factReads = mutableListOf<Long>()
    private val harness = FactEntryNavigationHarness(context) { api -> object : ApiService by api {
        override suspend fun debts(lens: String?) = DebtListResponseDto(emptyList(), "CNY")
        override suspend fun createManualExpense(request: ExpenseManualCreateRequestDto): ExpenseDto {
            sends++
            error("Only the worker may send the persisted original")
        }
        override suspend fun expense(id: Long): ExpenseDto {
            factReads += id
            return api.expense(id)
        }
    } }
    private val mounted = mutableStateOf(true)

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun shortcutSaveClosesTheSheetAndOpensTheExactOriginalFromItsAcceptanceFeedback() {
        compose.setContent {
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Default) {
                    if (mounted.value) {
                        val nav = rememberNavController()
                        NavHost(nav, startDestination = "manual-ledger") {
                            composable("manual-ledger") { LedgerRoute(nav, harness.shell, harness.screenFactory) }
                            addManualExpenseSubmissionRoute(MainNavigationRuntime(nav, harness.shell, harness.screenFactory))
                            composable(EXPENSE_ROUTE, arguments = listOf(navArgument(EXPENSE_ID_ARG) { type = NavType.LongType })) { entry ->
                                ExpenseEditRoute(requireNotNull(entry.arguments).getLong(EXPENSE_ID_ARG), harness.screenFactory,
                                    { nav.popBackStack() }, { nav.popBackStack() }, ExpenseFactNavigation({}, { _, _ -> }))
                            }
                        }
                    }
                }
            }
        }
        compose.runOnIdle { harness.shell.launchAction.post(LaunchAction.OpenManualEntry) }
        val saveLabel = context.getString(R.string.ledger_manual_save_button)
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(saveLabel)).fetchSemanticsNodes().isNotEmpty() }
        val amount = compose.onAllNodes(hasSetTextAction())[0]
        amount.performTextInput("12")
        amount.assertTextEquals("12")
        closeSoftKeyboard()
        compose.waitForIdle()
        compose.onNodeWithText(saveLabel).performScrollTo().performClick()
        compose.waitUntil(5_000) { harness.fixture.stored().size == 1 }
        val original = harness.fixture.stored().single()
        val request = requireNotNull(OutboxAdapterGraph().manualCreateAdapter.fromJson(requireNotNull(original["payload"])))
        assertEquals("12.00", request.originalAmount)
        assertEquals("CNY", request.homeCurrencyCode)
        assertEquals(0, sends)
        val local = runBlocking { harness.fixture.expenseDao.getConfirmed("correction-ledger").single { it.clientRef == request.clientRef } }
        assertTrue(local.serverId == null)
        // Ordinary sync can insert the server row before its original ACK promotes identity.
        // A pending FX receipt also removes the record from the confirmed cache read path.
        runBlocking {
            val pending = harness.fixture.network.current.copy(id = 71, publicId = "pending-manual-71",
                status = "pending", amountCents = null, homeAmountCents = null, fxStatus = "pending")
                .toEntity("correction-ledger")
            harness.fixture.expenseDao.upsertByServerIdForLedger("correction-ledger", pending)
            harness.fixture.expenseDao.applyLocalCreateServerIdentity("correction-ledger", pending.copy(clientRef = request.clientRef))
            assertTrue(harness.fixture.expenseDao.getConfirmed("correction-ledger").none { it.id == local.id })
            val promoted = harness.fixture.expenseDao.getPending("correction-ledger").single { it.clientRef == request.clientRef }
            assertTrue(promoted.id != local.id)
        }
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(saveLabel)).fetchSemanticsNodes().isEmpty() }
        compose.onNodeWithText(context.getString(R.string.ledger_msg_manual_saved_offline)).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.manual_submission_view_original)).performScrollTo().performClick()
        compose.waitUntil(5_000) { compose.onAllNodes(hasText("CNY 12.00")).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("CNY 12.00").assertIsDisplayed()
        assertTrue(factReads.none { it < 0 })
    }

    @Test fun localEntryOpensItsOriginalMoneyAndStopRemovesOnlyThatUnpromotedRecord() {
        val expense = runBlocking { harness.screenFactory.repository.createManualExpense(ExpenseDraft(
            amountCents = 1200, originalAmountMinor = 1200, originalCurrencyCode = CurrencyCode.CNY,
            ledgerHomeCurrency = CurrencyCode.CNY, merchant = "Original shop", category = "其他", note = null,
            expenseTime = "2026-09-09T00:00:00Z", tags = null, valueScore = null, regretScore = null)).getOrThrow() }
        compose.setContent {
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Default) {
                    if (mounted.value) ExpenseEditRoute(expense.id, harness.screenFactory, {}, {}, ExpenseFactNavigation({}, { _, _ -> }))
                }
            }
        }
        compose.waitUntil(5_000) { compose.onAllNodes(hasText("CNY 12.00")).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText("CNY 12.00").assertIsDisplayed()
        assertTrue(factReads.none { it < 0 })
        assertEquals(0, sends)
        runBlocking {
            val original = harness.fixture.outbox.observeActiveByTypes(setOf(PendingMutationType.CreateExpense)).first().single()
            harness.fixture.outbox.markFailed(original.id, "manual_create_original_requires_review")
        }
        val drop = context.getString(R.string.sync_status_failed_button_drop)
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(drop)).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText(drop).performScrollTo().performClick()
        compose.onNode(hasText(context.getString(R.string.manual_submission_stop)) and hasClickAction()).performClick()
        compose.waitUntil(5_000) { harness.fixture.stored().isEmpty() }
        assertTrue(runBlocking { harness.fixture.expenseDao.getConfirmed("correction-ledger").none { it.clientRef == expense.clientRef } })
        assertTrue(factReads.none { it < 0 })
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(context.getString(R.string.manual_submission_missing))).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText(context.getString(R.string.manual_submission_missing)).assertIsDisplayed()
    }
}

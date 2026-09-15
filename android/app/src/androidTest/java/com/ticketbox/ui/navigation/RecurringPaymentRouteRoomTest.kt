package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.closeSoftKeyboard
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtListResponseDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.repository.expenseAcceptanceReceiptJson
import com.ticketbox.data.repository.toEntity
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.ui.theme.TicketboxTheme
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Actual RecurringPaymentRoute, Room admission, Back/reopen draft, and Done receipt. */
class RecurringPaymentRouteRoomTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private var sends = 0
    private val harness = FactEntryNavigationHarness(context) { api -> object : ApiService by api {
        override suspend fun debts(lens: String?) = DebtListResponseDto(emptyList(), "CNY")
        override suspend fun createManualExpense(request: ExpenseManualCreateRequestDto): ExpenseDto {
            sends++
            error("Only the worker may send the persisted original")
        }
    } }
    private val mounted = mutableStateOf(true)
    private val drafts = RecurringPaymentDraftStore(SavedStateHandle())

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun ordinaryBackReopensClearedAmountMerchantAndChosenCurrencyWithoutRefillingSuggestions() {
        val task = periodTask(recorded = null, amount = null)
        showRoute(task)
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.occurrence_payment_currency))).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithText("JPY · 日元").performClick()
        waitForSheet()
        compose.onNode(hasSetTextAction() and hasText("房租")).performTextReplacement("")
        compose.onAllNodes(hasSetTextAction())[0].performTextReplacement("")
        compose.onNode(hasSetTextAction() and hasText("餐饮")).performTextReplacement("住房")
        compose.onNode(hasSetTextAction() and hasText("餐饮")).assertDoesNotExist()
        compose.onAllNodes(hasSetTextAction())[3].performTextReplacement("自填备注")
        closeSoftKeyboard()
        compose.waitForIdle()
        val stored = requireNotNull(drafts.read(task.clientRef))
        assertEquals("", stored.amountText)
        assertEquals("", stored.merchant)
        assertEquals("JPY", stored.currencyCode)
        assertEquals("住房", stored.category)
        assertEquals("自填备注", stored.note)
        compose.runOnIdle { mounted.value = false }
        compose.waitForIdle()
        compose.runOnIdle { mounted.value = true }
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.ledger_manual_sheet_title))).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithText(context.getString(R.string.occurrence_payment_currency)).assertDoesNotExist()
        compose.onNode(hasSetTextAction() and hasText("房租")).assertDoesNotExist()
        val restored = requireNotNull(drafts.read(task.clientRef))
        assertEquals("", restored.amountText)
        assertEquals("", restored.merchant)
        assertEquals("JPY", restored.currencyCode)
        assertEquals("住房", restored.category)
        assertEquals("自填备注", restored.note)
        assertEquals(0, sends)
        assertTrue(harness.fixture.stored().isEmpty())
    }

    @Test fun routeCreateAdmitsTheOriginalOnceThenReopenShowsTheSameCommand() {
        val task = periodTask("JPY", 1200)
        showRoute(task)
        waitForSheet()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        compose.waitUntil(10_000) { harness.fixture.stored().size == 1 }
        val original = harness.fixture.stored().single()
        val request = requireNotNull(OutboxAdapterGraph().manualCreateAdapter.fromJson(requireNotNull(original["payload"])))
        assertEquals(task.clientRef, request.clientRef)
        assertEquals("JPY", request.originalCurrency)
        assertEquals("1200", request.originalAmount)
        assertEquals(0, sends)
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.manual_submission_waiting))).fetchSemanticsNodes().isNotEmpty() ||
                compose.onAllNodes(hasText(context.getString(R.string.manual_submission_title))).fetchSemanticsNodes().isNotEmpty()
        }
        compose.runOnIdle { mounted.value = false }
        compose.waitForIdle()
        compose.runOnIdle { mounted.value = true }
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.manual_submission_waiting))).fetchSemanticsNodes().isNotEmpty() ||
                compose.onAllNodes(hasText(context.getString(R.string.manual_submission_title))).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithText(context.getString(R.string.ledger_manual_sheet_title)).assertDoesNotExist()
        assertEquals(1, harness.fixture.stored().size)
        assertNull(drafts.read(task.clientRef))
    }

    @Test fun doneReceiptWithPendingFxOpensSubmissionIdentityInsteadOfTheCreateForm() {
        val task = periodTask("JPY", 1200)
        val draft = ExpenseDraft(
            amountCents = 1200, originalCurrencyCode = CurrencyCode.JPY, originalAmountMinor = 1200,
            ledgerHomeCurrency = CurrencyCode.CNY, merchant = "房租", category = "餐饮", note = null,
            expenseTime = "2026-08-15T00:00:00Z", tags = null, valueScore = null, regretScore = null,
        )
        runBlocking {
            harness.screenFactory.repository.manualCreation.create(draft, task.binding, task.clientRef).getOrThrow()
            val row = harness.fixture.outbox.observeActiveByTypes(setOf(PendingMutationType.CreateExpense), includeCompleted = true).first().single()
            harness.fixture.outbox.markDone(row.id, receiptJson = expenseAcceptanceReceiptJson(71))
            val pending = harness.fixture.network.current.copy(
                id = 71, publicId = "pending-fx-71", status = "pending",
                amountCents = null, homeAmountCents = null, fxStatus = "pending",
            ).toEntity("correction-ledger")
            harness.fixture.expenseDao.upsertByServerIdForLedger("correction-ledger", pending)
            harness.fixture.expenseDao.applyLocalCreateServerIdentity("correction-ledger", pending.copy(clientRef = task.clientRef))
        }
        showRoute(task)
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.manual_submission_done))).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithText(context.getString(R.string.manual_submission_done)).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_sheet_title)).assertDoesNotExist()
        val projection = runBlocking {
            harness.screenFactory.repository.manualCreation.observe(task.binding, task.clientRef).first()
        }
        assertEquals(71L, projection?.acceptedExpenseId)
        assertEquals(0, sends)
    }

    private fun showRoute(task: RecurringPaymentTask) {
        compose.setContent {
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Default) {
                    if (mounted.value) {
                        RecurringPaymentRoute(
                            task = task,
                            factory = harness.screenFactory,
                            exit = ExpenseEditExitActions({}, {}),
                            financialDataRevision = 0,
                            related = ExpenseFactNavigation({}, { _, _ -> }),
                            drafts = drafts,
                        )
                    }
                }
            }
        }
    }

    private fun waitForSheet() {
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.ledger_manual_sheet_title))).fetchSemanticsNodes().isNotEmpty()
        }
    }

    private fun periodTask(recorded: String?, amount: Long?): RecurringPaymentTask {
        val binding = requireNotNull(harness.screenFactory.repository.captureDeferredLedgerBinding())
        return RecurringPaymentTask(
            binding = binding,
            seriesPublicId = "rec-1",
            period = "2026-08",
            clientRef = "period-ref",
            merchant = "房租",
            recordedCurrencyCode = recorded,
            suggestedAmountMinor = amount,
            ledgerHomeCurrencyCode = "CNY",
        )
    }
}

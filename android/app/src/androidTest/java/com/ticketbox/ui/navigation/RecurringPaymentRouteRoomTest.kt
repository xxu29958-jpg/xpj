package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.closeSoftKeyboard
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtListResponseDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.RecurringPaymentOrigin
import com.ticketbox.data.repository.RecurringPaymentOriginAdopt
import com.ticketbox.data.repository.decodeRecurringPaymentOrigin
import com.ticketbox.data.repository.encodeManualCreatePayload
import com.ticketbox.data.repository.expenseAcceptanceReceiptJson
import com.ticketbox.data.repository.toEntity
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.RecurringOccurrenceUiState
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Actual RecurringPaymentRoute, Room admission, Back/reopen draft, and Done receipt. */
class RecurringPaymentRouteRoomTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private var sends = 0
    private var occurrenceReads = 0
    private var failOccurrenceReads = false
    private var currentOccurrenceGeneration = 3L
    private val harness = FactEntryNavigationHarness(context) { api -> object : ApiService by api {
        override suspend fun debts(lens: String?) = DebtListResponseDto(emptyList(), "CNY")
        override suspend fun createManualExpense(request: ExpenseManualCreateRequestDto): ExpenseDto {
            sends++
            error("Only the worker may send the persisted original")
        }
        override suspend fun recurringOccurrence(publicId: String, month: String): RecurringOccurrenceDto {
            occurrenceReads++
            check(!failOccurrenceReads) { "offline" }
            if (publicId != "rec-1") return api.recurringOccurrence(publicId, month)
            return RecurringOccurrenceDto(
                seriesPublicId = publicId,
                period = month,
                seriesRowVersion = 7,
                rowVersion = currentOccurrenceGeneration,
                state = "unfulfilled",
                plannedAmountCents = 1200,
                reservedAmountCents = 1200,
                expensePublicId = null,
                paidAmountCents = null,
                nextDueDate = "2026-08-15",
                homeCurrencyCode = "JPY",
            )
        }
    } }
    private val mounted = mutableStateOf(true)
    private val openedExpense = mutableStateOf<Long?>(null)
    private val exited = mutableStateOf(false)
    private val drafts = RecurringPaymentDraftStore(SavedStateHandle())
    private val routeTask = mutableStateOf<RecurringPaymentTask?>(null)
    private var routeContent = false

    @After fun close() {
        compose.runOnIdle { mounted.value = false; openedExpense.value = null; exited.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
        sends = 0
        occurrenceReads = 0
        failOccurrenceReads = false
        currentOccurrenceGeneration = 3L
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
        val task = periodTask("JPY", 1200).copy(occurrenceRowVersion = 3L)
        drafts.remember(task)
        showRoute(task)
        waitForSheet()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        compose.waitUntil(10_000) { harness.fixture.stored().size == 1 }
        val original = harness.fixture.stored().single()
        val request = requireNotNull(readCreateRequest(requireNotNull(original["payload"])))
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
        assertEquals(task.clientRef, drafts.remembered(task.binding, task.seriesPublicId, task.period)?.clientRef)
    }

    @Test fun admittedAugustThenSeptemberThenAugustReusesOriginalClientRefWithoutAnotherOutbox() {
        val august = periodTask("JPY", 1200).copy(clientRef = "august-ref", occurrenceRowVersion = 3L)
        drafts.remember(august)
        showRoute(august)
        waitForSheet()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        compose.waitUntil(10_000) { harness.fixture.stored().size == 1 }
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.manual_submission_waiting))).fetchSemanticsNodes().isNotEmpty() ||
                compose.onAllNodes(hasText(context.getString(R.string.manual_submission_title))).fetchSemanticsNodes().isNotEmpty()
        }
        assertNull(drafts.read("august-ref"))
        assertEquals("august-ref", drafts.remembered(august.binding, august.seriesPublicId, "2026-08")?.clientRef)
        compose.runOnIdle { mounted.value = false }
        compose.waitForIdle()
        val september = august.copy(clientRef = "september-ref", period = "2026-09")
        drafts.remember(september)
        val again = requireNotNull(
            recurringPaymentTask(
                augustUiState(august),
                existing = september,
                remembered = drafts.remembered(august.binding, august.seriesPublicId, "2026-08"),
            ),
        )
        assertEquals("august-ref", again.clientRef)
        assertEquals("2026-08", again.period)
        assertEquals(1, harness.fixture.stored().size)
        assertEquals(0, sends)
        showRoute(again)
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.manual_submission_waiting))).fetchSemanticsNodes().isNotEmpty() ||
                compose.onAllNodes(hasText(context.getString(R.string.manual_submission_title))).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithText(context.getString(R.string.ledger_manual_sheet_title)).assertDoesNotExist()
        assertEquals(1, harness.fixture.stored().size)
        assertEquals("august-ref", drafts.remembered(august.binding, august.seriesPublicId, "2026-08")?.clientRef)
        assertEquals("september-ref", drafts.remembered(september.binding, september.seriesPublicId, "2026-09")?.clientRef)
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

    @Test fun knownSuggestedAmountClearedSurvivesReopenWithoutRefillingPrefill() {
        val task = periodTask("JPY", 1200)
        showRoute(task)
        waitForSheet()
        compose.onNode(hasSetTextAction() and hasText("1200")).assertIsDisplayed()
        compose.onNode(hasSetTextAction() and hasText("1200")).performTextReplacement("")
        compose.onNode(hasSetTextAction() and hasText("房租")).performTextReplacement("")
        closeSoftKeyboard()
        compose.waitForIdle()
        assertEquals("", drafts.read(task.clientRef)?.amountText)
        assertEquals("", drafts.read(task.clientRef)?.merchant)
        compose.runOnIdle { mounted.value = false }
        compose.waitForIdle()
        compose.runOnIdle { mounted.value = true }
        waitForSheet()
        compose.onNode(hasSetTextAction() and hasText("1200")).assertDoesNotExist()
        compose.onNode(hasSetTextAction() and hasText("房租")).assertDoesNotExist()
        assertEquals("", requireNotNull(drafts.read(task.clientRef)).amountText)
        assertEquals("", requireNotNull(drafts.read(task.clientRef)).merchant)
        assertEquals(0, sends)
        assertTrue(harness.fixture.stored().isEmpty())
    }

    @Test fun navBackStackAugustThenSeptemberThenAugustRestoresClearedAugustPrefill() {
        val august = periodTask("JPY", 1200).copy(clientRef = "august-ref")
        val september = periodTask("JPY", 1200).copy(clientRef = "september-ref", period = "2026-09")
        val navHolder = mutableStateOf<NavHostController?>(null)
        val restored = mutableStateOf<RecurringPaymentTask?>(null)
        compose.setContent {
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Default) {
                    val nav = rememberNavController()
                    navHolder.value = nav
                    NavHost(nav, startDestination = MAIN_ROUTE) {
                        composable(MAIN_ROUTE) { entry ->
                            androidx.compose.runtime.CompositionLocalProvider(
                                LocalRecurringPaymentDraftHandle provides entry.savedStateHandle,
                            ) { }
                        }
                        addRecurringPaymentRoute(MainNavigationRuntime(nav, harness.shell, harness.screenFactory))
                    }
                }
            }
        }
        compose.waitUntil(10_000) { navHolder.value != null }
        compose.runOnIdle {
            val nav = requireNotNull(navHolder.value)
            RecurringPaymentDraftStore(nav.getBackStackEntry(MAIN_ROUTE).savedStateHandle)
                .remember(august)
            nav.navigate(recurringPaymentRoute(august))
        }
        waitForSheet()
        compose.onNode(hasSetTextAction() and hasText("1200")).performTextReplacement("")
        compose.onNode(hasSetTextAction() and hasText("房租")).performTextReplacement("")
        compose.onNode(hasSetTextAction() and hasText("餐饮")).performTextReplacement("住房")
        compose.onAllNodes(hasSetTextAction())[3].performTextReplacement("自填备注")
        closeSoftKeyboard()
        compose.waitForIdle()
        lateinit var augustTime: String
        compose.runOnIdle {
            val stored = requireNotNull(
                RecurringPaymentDraftStore(
                    requireNotNull(navHolder.value).getBackStackEntry(MAIN_ROUTE).savedStateHandle,
                ).read("august-ref"),
            )
            assertEquals("", stored.amountText)
            assertEquals("", stored.merchant)
            assertEquals("JPY", stored.currencyCode)
            assertEquals("住房", stored.category)
            assertEquals("自填备注", stored.note)
            assertTrue(stored.expenseTime.isNotBlank())
            augustTime = stored.expenseTime
        }
        compose.runOnIdle { requireNotNull(navHolder.value).popBackStack() }
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.ledger_manual_sheet_title))).fetchSemanticsNodes().isEmpty()
        }
        compose.runOnIdle {
            val nav = requireNotNull(navHolder.value)
            RecurringPaymentDraftStore(nav.getBackStackEntry(MAIN_ROUTE).savedStateHandle)
                .remember(september)
            nav.navigate(recurringPaymentRoute(september))
        }
        waitForSheet()
        compose.onNode(hasSetTextAction() and hasText("1200")).assertIsDisplayed()
        compose.runOnIdle { requireNotNull(navHolder.value).popBackStack() }
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.ledger_manual_sheet_title))).fetchSemanticsNodes().isEmpty()
        }
        compose.runOnIdle {
            val nav = requireNotNull(navHolder.value)
            val store = RecurringPaymentDraftStore(
                nav.getBackStackEntry(MAIN_ROUTE).savedStateHandle,
            )
            val again = requireNotNull(
                recurringPaymentTask(
                    augustUiState(august),
                    existing = september,
                    remembered = store.remembered(august.binding, august.seriesPublicId, august.period),
                ),
            )
            restored.value = again
            nav.navigate(recurringPaymentRoute(again))
        }
        waitForSheet()
        compose.onNode(hasSetTextAction() and hasText("1200")).assertDoesNotExist()
        compose.onNode(hasSetTextAction() and hasText("房租")).assertDoesNotExist()
        compose.onNode(hasSetTextAction() and hasText("住房")).assertIsDisplayed()
        compose.onNode(hasSetTextAction() and hasText("自填备注")).assertIsDisplayed()
        assertEquals("august-ref", restored.value?.clientRef)
        compose.runOnIdle {
            val store = RecurringPaymentDraftStore(
                requireNotNull(navHolder.value).getBackStackEntry(MAIN_ROUTE).savedStateHandle,
            )
            val draft = requireNotNull(store.read("august-ref"))
            assertEquals("", draft.amountText)
            assertEquals("", draft.merchant)
            assertEquals("JPY", draft.currencyCode)
            assertEquals("住房", draft.category)
            assertEquals("自填备注", draft.note)
            assertEquals(augustTime, draft.expenseTime)
        }
        assertEquals(0, sends)
        assertTrue(harness.fixture.stored().isEmpty())
    }

    @Test fun reviewShowsUnattributedFactsAndAdoptBindsWithoutCreating() {
        val task = periodTask("CNY", 10_000).copy(occurrenceRowVersion = 3L)
        enqueueRaw(task, "legacy-ref", "便利店", CurrencyCode.CNY, 8800, "2026-08-01T00:00:00Z")
        drafts.write(
            RecurringPaymentDraft(
                clientRef = task.clientRef,
                amountText = "10.00",
                currencyCode = "CNY",
                merchant = task.merchant,
                category = "住房",
                note = "旧草稿",
                expenseTime = "",
            ),
        )
        drafts.remember(task)
        showRoute(task)
        waitForSheet()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        waitForReview()
        compose.onNodeWithText(context.getString(R.string.recurring_payment_review_original)).assertIsDisplayed()
        compose.onNodeWithText("便利店").assertIsDisplayed()
        compose.onNodeWithText("CNY 88.00").assertIsDisplayed()
        compose.onNodeWithText("2026-08-01T00:00:00Z").assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.manual_submission_waiting)).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.manual_submission_unknown)).assertDoesNotExist()
        compose.onNodeWithTag("recurring-payment-review-adopt:legacy-ref").performClick()
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.recurring_payment_review_required))).fetchSemanticsNodes().isEmpty()
        }
        compose.onNodeWithText(context.getString(R.string.ledger_manual_sheet_title)).assertExists()
        compose.onNodeWithTag("recurring-payment-local-draft").assertIsDisplayed()
        assertEquals(1, harness.fixture.stored().size)
        assertEquals(task.clientRef, drafts.remembered(task.binding, task.seriesPublicId, task.period)?.clientRef)
        assertNotNull(drafts.read(task.clientRef))
        assertEquals("旧草稿", drafts.read(task.clientRef)?.note)
        val stored = requireNotNull(
            decodeRecurringPaymentOrigin(
                OutboxAdapterGraph().recurringPaymentCreateAdapter,
                requireNotNull(harness.fixture.stored().single()["payload"]),
            ),
        )
        assertEquals(RecurringPaymentOrigin(task.seriesPublicId, task.period, 3L), stored)
        assertEquals("legacy-ref", readCreateRequest(requireNotNull(harness.fixture.stored().single()["payload"])).clientRef)
        compose.onNodeWithText(context.getString(R.string.common_cancel)).performClick()
        compose.waitUntil(10_000) { exited.value }
        assertEquals(0, sends)
    }

    @Test fun reviewShowsDoneStatusAndExistingExpenseOutlet() {
        val task = periodTask("CNY", 10_000).copy(occurrenceRowVersion = 3L)
        enqueueRaw(task, "legacy-ref", "便利店", CurrencyCode.CNY, 8800, "2026-08-01T00:00:00Z")
        runBlocking {
            val row = harness.fixture.outbox
                .observeActiveByTypes(setOf(PendingMutationType.CreateExpense), includeCompleted = true)
                .first()
                .single()
            harness.fixture.outbox.markDone(row.id, receiptJson = expenseAcceptanceReceiptJson(71))
        }
        drafts.remember(task)
        showRoute(task)
        waitForSheet()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        waitForReview()
        compose.onNodeWithText(context.getString(R.string.manual_submission_done)).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.manual_submission_unknown)).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.manual_submission_waiting)).assertDoesNotExist()
        compose.onNodeWithTag("recurring-payment-review-open:71").performClick()
        assertEquals(71L, openedExpense.value)
        assertEquals(1, harness.fixture.stored().size)
        assertEquals(0, sends)
    }

    @Test fun reviewShowsFailedStatusInsteadOfWaiting() {
        val task = periodTask("CNY", 10_000).copy(occurrenceRowVersion = 3L)
        enqueueRaw(task, "legacy-ref", "便利店", CurrencyCode.CNY, 8800, "2026-08-01T00:00:00Z")
        runBlocking {
            val row = harness.fixture.outbox
                .observeActiveByTypes(setOf(PendingMutationType.CreateExpense), includeCompleted = true)
                .first()
                .single()
            harness.fixture.outbox.markFailed(row.id, "gone")
        }
        drafts.remember(task)
        showRoute(task)
        waitForSheet()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        waitForReview()
        compose.onNodeWithText(context.getString(R.string.sync_status_failed_fallback)).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.manual_submission_waiting)).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.manual_submission_unknown)).assertDoesNotExist()
        assertEquals(1, harness.fixture.stored().size)
        assertEquals(0, sends)
    }

    @Test fun adoptMissingKeepsTheDraftAndDoesNotCreateWithTheStaleRef() {
        val task = periodTask("CNY", 10_000).copy(occurrenceRowVersion = 3L)
        enqueueRaw(task, "legacy-ref", "便利店", CurrencyCode.CNY, 8800, "2026-08-01T00:00:00Z")
        drafts.remember(task)
        showRoute(task)
        waitForSheet()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        waitForReview()
        stopDisplayedRaw()
        compose.onNodeWithTag("recurring-payment-review-adopt:legacy-ref").performClick()
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.recurring_payment_review_missing))).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithTag("recurring-payment-review-error").assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_sheet_title)).assertExists()
        compose.onNodeWithText("房租").assertExists()
        assertTrue(harness.fixture.stored().isEmpty())
        assertEquals(task.clientRef, drafts.remembered(task.binding, task.seriesPublicId, task.period)?.clientRef)
        assertEquals(0, sends)
        compose.onNodeWithTag("recurring-payment-review-dismiss").performClick()
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.recurring_payment_review_required))).fetchSemanticsNodes().isEmpty()
        }
        compose.waitForIdle()
        compose.onNodeWithTag("recurring-payment-review-error").assertDoesNotExist()
        waitForSheet()
        compose.onNodeWithText("房租").assertExists()
        assertEquals(task.clientRef, drafts.remembered(task.binding, task.seriesPublicId, task.period)?.clientRef)
        assertEquals(0, sends)
        compose.onNodeWithText(context.getString(R.string.common_cancel)).performClick()
        compose.waitUntil(10_000) { exited.value }
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.ledger_manual_sheet_title))).fetchSemanticsNodes().isEmpty()
        }
    }

    @Test fun reviewBackThenSheetBackExits() {
        val task = periodTask("CNY", 10_000).copy(occurrenceRowVersion = 3L)
        enqueueRaw(task, "legacy-ref", "便利店", CurrencyCode.CNY, 8800, "2026-08-01T00:00:00Z")
        drafts.remember(task)
        showRoute(task)
        waitForSheet()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        waitForReview()
        compose.onNodeWithTag("recurring-payment-review-dismiss").performClick()
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.recurring_payment_review_required))).fetchSemanticsNodes().isEmpty()
        }
        waitForSheet()
        assertEquals(false, exited.value)
        compose.onNodeWithText(context.getString(R.string.common_cancel)).performClick()
        compose.waitUntil(10_000) { exited.value }
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.ledger_manual_sheet_title))).fetchSemanticsNodes().isEmpty()
        }
    }

    @Test fun ordinaryCreateFailureDoesNotOpenReview() {
        val task = periodTask("CNY", 10_000).copy(occurrenceRowVersion = 3L)
        val origin = RecurringPaymentOrigin(task.seriesPublicId, task.period, 3L)
        enqueueRaw(task, "dup-a", "便利店", CurrencyCode.CNY, 8800, "2026-08-01T00:00:00Z", origin)
        enqueueRaw(task, "dup-b", "超市", CurrencyCode.JPY, 1500, "2026-08-15T12:00:00Z")
        runBlocking {
            val row = harness.fixture.outbox
                .observeActiveByTypes(setOf(PendingMutationType.CreateExpense), includeCompleted = true)
                .first()
                .single { it.targetId == "expense:local:dup-b" }
            val request = readCreateRequest(requireNotNull(row.payloadJson))
            check(
                harness.fixture.outbox.replaceCreateExpensePayload(
                    row.id,
                    encodeManualCreatePayload(
                        OutboxAdapterGraph().manualCreateAdapter,
                        OutboxAdapterGraph().recurringPaymentCreateAdapter,
                        request,
                        origin,
                    ),
                ),
            )
        }
        drafts.remember(task)
        showRoute(task)
        waitForSheet()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText("本期付款命令冲突，请先处理重复提交。")).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithText(context.getString(R.string.recurring_payment_review_required)).assertDoesNotExist()
        waitForSheet()
        assertEquals(task.clientRef, drafts.remembered(task.binding, task.seriesPublicId, task.period)?.clientRef)
        assertEquals(2, harness.fixture.stored().size)
        assertEquals(0, sends)
    }

    @Test fun adoptConflictKeepsTheDraftAndDoesNotRebind() {
        val task = periodTask("CNY", 10_000).copy(occurrenceRowVersion = 3L)
        enqueueRaw(task, "legacy-ref", "便利店", CurrencyCode.CNY, 8800, "2026-08-01T00:00:00Z")
        drafts.remember(task)
        showRoute(task)
        waitForSheet()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        waitForReview()
        runBlocking {
            assertEquals(
                RecurringPaymentOriginAdopt.Bound,
                harness.screenFactory.repository.manualCreation.adoptOrigin(
                    task.binding, "legacy-ref", "rec-other", "2026-07", 1L,
                ),
            )
        }
        compose.onNodeWithTag("recurring-payment-review-adopt:legacy-ref").performClick()
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.recurring_payment_review_conflict))).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithText(context.getString(R.string.ledger_manual_sheet_title)).assertExists()
        compose.onNodeWithText("房租").assertExists()
        assertEquals(1, harness.fixture.stored().size)
        assertEquals(
            RecurringPaymentOrigin("rec-other", "2026-07", 1L),
            decodeRecurringPaymentOrigin(
                OutboxAdapterGraph().recurringPaymentCreateAdapter,
                requireNotNull(harness.fixture.stored().single()["payload"]),
            ),
        )
        assertEquals(task.clientRef, drafts.remembered(task.binding, task.seriesPublicId, task.period)?.clientRef)
        assertEquals(0, sends)
    }

    @Test fun reviewShowsTwoCandidatesAndAdoptOnlyBindsTheChosen() {
        val task = periodTask("CNY", 10_000).copy(occurrenceRowVersion = 3L)
        enqueueRaw(task, "legacy-c", "便利店", CurrencyCode.CNY, 8800, "2026-08-01T00:00:00Z")
        enqueueRaw(task, "legacy-d", "超市", CurrencyCode.JPY, 1500, "2026-08-15T12:00:00Z")
        drafts.write(
            RecurringPaymentDraft(
                clientRef = task.clientRef,
                amountText = "10.00",
                currencyCode = "CNY",
                merchant = task.merchant,
                category = "住房",
                note = "当前草稿",
                expenseTime = "",
            ),
        )
        drafts.remember(task)
        showRoute(task)
        waitForSheet()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        waitForReview()
        compose.onNodeWithText("便利店").assertIsDisplayed()
        compose.onNodeWithText("CNY 88.00").assertIsDisplayed()
        compose.onNodeWithText("2026-08-01T00:00:00Z").assertIsDisplayed()
        compose.onNodeWithText("超市").assertIsDisplayed()
        compose.onNodeWithText("JPY 1500").assertIsDisplayed()
        compose.onNodeWithText("2026-08-15T12:00:00Z").assertIsDisplayed()
        compose.onNodeWithTag("recurring-payment-review-adopt:legacy-c").assertIsDisplayed()
        compose.onNodeWithTag("recurring-payment-review-adopt:legacy-d").assertIsDisplayed()
        val beforeD = requireNotNull(harness.fixture.stored().single { it["targetId"] == "expense:local:legacy-d" }["payload"])
        compose.onNodeWithTag("recurring-payment-review-adopt:legacy-c").performClick()
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.recurring_payment_review_required))).fetchSemanticsNodes().isEmpty()
        }
        compose.onNodeWithText(context.getString(R.string.ledger_manual_sheet_title)).assertExists()
        compose.onNodeWithTag("recurring-payment-local-draft").assertIsDisplayed()
        assertEquals(2, harness.fixture.stored().size)
        assertEquals(task.clientRef, drafts.remembered(task.binding, task.seriesPublicId, task.period)?.clientRef)
        assertNotNull(drafts.read(task.clientRef))
        assertEquals(
            RecurringPaymentOrigin(task.seriesPublicId, task.period, 3L),
            decodeRecurringPaymentOrigin(
                OutboxAdapterGraph().recurringPaymentCreateAdapter,
                requireNotNull(harness.fixture.stored().single { it["targetId"] == "expense:local:legacy-c" }["payload"]),
            ),
        )
        assertEquals(beforeD, harness.fixture.stored().single { it["targetId"] == "expense:local:legacy-d" }["payload"])
        assertNull(
            decodeRecurringPaymentOrigin(
                OutboxAdapterGraph().recurringPaymentCreateAdapter,
                beforeD,
            ),
        )
        assertEquals(0, sends)
    }

    @Test fun confirmUnrelatedAfterNewCandidateAppearsRequiresReviewAgain() {
        val task = periodTask("CNY", 10_000).copy(occurrenceRowVersion = 3L)
        enqueueRaw(task, "legacy-c", "便利店", CurrencyCode.CNY, 8800, "2026-08-01T00:00:00Z")
        drafts.remember(task)
        showRoute(task)
        waitForSheet()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        waitForReview()
        compose.onNodeWithTag("recurring-payment-review-adopt:legacy-c").assertIsDisplayed()
        enqueueRaw(task, "legacy-d", "超市", CurrencyCode.JPY, 1500, "2026-08-15T12:00:00Z")
        compose.onNodeWithTag("recurring-payment-review-not-this-period").performClick()
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText("超市")).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithText(context.getString(R.string.ledger_manual_sheet_title)).assertExists()
        compose.onNodeWithTag("recurring-payment-review-adopt:legacy-c").assertIsDisplayed()
        compose.onNodeWithTag("recurring-payment-review-adopt:legacy-d").assertIsDisplayed()
        assertEquals(2, harness.fixture.stored().size)
        assertTrue(harness.fixture.stored().none { it["targetId"] == "expense:local:period-ref" })
        assertEquals(task.clientRef, drafts.remembered(task.binding, task.seriesPublicId, task.period)?.clientRef)
        assertEquals(0, sends)
    }

    @Test fun reopeningUnversionedCurrentDraftSaveReusesOriginAWithoutSecondCreate() {
        val origin = periodTask("JPY", 1200).copy(clientRef = "origin-a", occurrenceRowVersion = 3L)
        enqueueRaw(
            origin, "origin-a", "房租", CurrencyCode.JPY, 1200, "2026-08-01T00:00:00Z",
            RecurringPaymentOrigin("rec-1", "2026-08", 3L),
        )
        val localB = periodTask("JPY", 1200).copy(clientRef = "current-b")
        assertNull(localB.occurrenceRowVersion)
        drafts.remember(localB)
        drafts.write(
            RecurringPaymentDraft(
                clientRef = "current-b",
                amountText = "99.00",
                currencyCode = "JPY",
                merchant = "改过的商户",
                category = "住房",
                note = "当前草稿",
                expenseTime = "2026-08-01T00:00:00Z",
            ),
        )
        showRoute(localB.copy(occurrenceRowVersion = 3L))
        waitForSheet()
        compose.onNodeWithTag("recurring-payment-local-draft").assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        compose.waitForIdle()
        compose.onNodeWithTag("recurring-payment-local-draft").assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_sheet_title)).assertExists()
        assertEquals(1, harness.fixture.stored().size)
        assertEquals("origin-a", readCreateRequest(requireNotNull(harness.fixture.stored().single()["payload"])).clientRef)
        assertEquals(
            RecurringPaymentOrigin("rec-1", "2026-08", 3L),
            decodeRecurringPaymentOrigin(
                OutboxAdapterGraph().recurringPaymentCreateAdapter,
                requireNotNull(harness.fixture.stored().single()["payload"]),
            ),
        )
        assertEquals("当前草稿", drafts.read("current-b")?.note)
        assertEquals("current-b", drafts.remembered(localB.binding, localB.seriesPublicId, localB.period)?.clientRef)
        assertEquals(0, sends)
    }

    @Test fun restoringUnversionedWritableRouteSaveKeepsOriginAWithoutSecondCreate() {
        currentOccurrenceGeneration = 7L
        val origin = periodTask("JPY", 1200).copy(clientRef = "origin-a", occurrenceRowVersion = 7L)
        enqueueRaw(
            origin, "origin-a", "房租", CurrencyCode.JPY, 1200, "2026-08-01T00:00:00Z",
            RecurringPaymentOrigin("rec-1", "2026-08", 7L),
        )
        val localB = periodTask("JPY", 1200).copy(clientRef = "current-b")
        assertNull(localB.occurrenceRowVersion)
        drafts.remember(localB)
        drafts.write(
            RecurringPaymentDraft(
                clientRef = "current-b",
                amountText = "99.00",
                currencyCode = "JPY",
                merchant = "改过的商户",
                category = "住房",
                note = "当前草稿",
                expenseTime = "2026-08-01T00:00:00Z",
            ),
        )
        showRoute(localB)
        waitForSheet()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.recurring_payment_generation_changed))).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithText(context.getString(R.string.ledger_manual_sheet_title)).assertExists()
        assertEquals(1, harness.fixture.stored().size)
        assertEquals("origin-a", readCreateRequest(requireNotNull(harness.fixture.stored().single()["payload"])).clientRef)
        assertTrue(harness.fixture.stored().none { it["targetId"] == "expense:local:current-b" })
        assertEquals("当前草稿", drafts.read("current-b")?.note)
        assertEquals("current-b", drafts.remembered(localB.binding, localB.seriesPublicId, localB.period)?.clientRef)
        assertEquals(0, sends)
        assertEquals(0, occurrenceReads)
    }

    @Test fun openFormThenOccurrenceAdvancesSaveDoesNotEnqueueStaleGeneration() {
        currentOccurrenceGeneration = 5L
        val localB = periodTask("JPY", 1200).copy(clientRef = "current-b", occurrenceRowVersion = 5L)
        drafts.remember(localB)
        drafts.write(
            RecurringPaymentDraft(
                clientRef = "current-b",
                amountText = "99.00",
                currencyCode = "JPY",
                merchant = "改过的商户",
                category = "住房",
                note = "当前草稿",
                expenseTime = "2026-08-01T00:00:00Z",
            ),
        )
        showRoute(localB)
        waitForSheet()
        currentOccurrenceGeneration = 7L
        enqueueRaw(
            localB.copy(clientRef = "origin-a", occurrenceRowVersion = 7L),
            "origin-a", "房租", CurrencyCode.JPY, 1200, "2026-08-01T00:00:00Z",
            RecurringPaymentOrigin("rec-1", "2026-08", 7L),
        )
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.recurring_payment_generation_changed))).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithText(context.getString(R.string.ledger_manual_sheet_title)).assertExists()
        assertEquals(1, harness.fixture.stored().size)
        assertEquals("origin-a", readCreateRequest(requireNotNull(harness.fixture.stored().single()["payload"])).clientRef)
        assertEquals(
            RecurringPaymentOrigin("rec-1", "2026-08", 7L),
            decodeRecurringPaymentOrigin(
                OutboxAdapterGraph().recurringPaymentCreateAdapter,
                requireNotNull(harness.fixture.stored().single()["payload"]),
            ),
        )
        assertTrue(harness.fixture.stored().none { it["targetId"] == "expense:local:current-b" })
        assertEquals("当前草稿", drafts.read("current-b")?.note)
        assertEquals("current-b", drafts.remembered(localB.binding, localB.seriesPublicId, localB.period)?.clientRef)
        assertEquals(0, sends)
        assertEquals(0, occurrenceReads)
    }

    @Test fun hostStampedSaveWritesOutboxWhileOccurrenceApiIsOffline() {
        failOccurrenceReads = true
        val localB = periodTask("JPY", 1200).copy(clientRef = "current-b", occurrenceRowVersion = 5L)
        drafts.remember(localB)
        drafts.write(
            RecurringPaymentDraft(
                clientRef = "current-b",
                amountText = "99.00",
                currencyCode = "JPY",
                merchant = "改过的商户",
                category = "住房",
                note = "当前草稿",
                expenseTime = "2026-08-01T00:00:00Z",
            ),
        )
        showRoute(localB)
        waitForSheet()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        compose.waitUntil(10_000) { harness.fixture.stored().size == 1 }
        val stored = harness.fixture.stored().single()
        assertEquals("expense:local:current-b", stored["targetId"])
        assertEquals("current-b", readCreateRequest(requireNotNull(stored["payload"])).clientRef)
        assertEquals(
            RecurringPaymentOrigin("rec-1", "2026-08", 5L),
            decodeRecurringPaymentOrigin(
                OutboxAdapterGraph().recurringPaymentCreateAdapter,
                requireNotNull(stored["payload"]),
            ),
        )
        assertEquals("current-b", drafts.remembered(localB.binding, localB.seriesPublicId, localB.period)?.clientRef)
        assertEquals(0, sends)
        assertEquals(0, occurrenceReads)
    }

    @Test fun restoringUnversionedWritableRouteSaveKeepsDraftWithoutOccurrenceGet() {
        failOccurrenceReads = true
        val localB = periodTask("JPY", 1200).copy(clientRef = "current-b")
        assertNull(localB.occurrenceRowVersion)
        drafts.remember(localB)
        drafts.write(
            RecurringPaymentDraft(
                clientRef = "current-b",
                amountText = "99.00",
                currencyCode = "JPY",
                merchant = "改过的商户",
                category = "住房",
                note = "当前草稿",
                expenseTime = "2026-08-01T00:00:00Z",
            ),
        )
        showRoute(localB)
        waitForSheet()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.recurring_payment_generation_changed))).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithText(context.getString(R.string.ledger_manual_sheet_title)).assertExists()
        assertTrue(harness.fixture.stored().isEmpty())
        assertEquals("当前草稿", drafts.read("current-b")?.note)
        assertEquals("current-b", drafts.remembered(localB.binding, localB.seriesPublicId, localB.period)?.clientRef)
        assertEquals(0, sends)
        assertEquals(0, occurrenceReads)
    }

    private fun waitForReview() {
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.recurring_payment_review_required))).fetchSemanticsNodes().isNotEmpty()
        }
    }

    private fun enqueueRaw(
        task: RecurringPaymentTask,
        ref: String,
        merchant: String,
        currency: CurrencyCode,
        originalAmountMinor: Long,
        expenseTime: String,
        origin: RecurringPaymentOrigin? = null,
    ) = enqueueRawPeriodPayment(
        harness.screenFactory.repository.manualCreation,
        task, ref, merchant, currency, originalAmountMinor, expenseTime, origin,
    )

    private fun stopDisplayedRaw() {
        runBlocking {
            val row = harness.fixture.outbox
                .observeActiveByTypes(setOf(PendingMutationType.CreateExpense), includeCompleted = true)
                .first()
                .single()
            harness.fixture.outbox.markFailed(row.id, "gone")
            val failed = harness.fixture.outbox
                .observeActiveByTypes(setOf(PendingMutationType.CreateExpense), includeCompleted = true)
                .first()
                .single()
            harness.screenFactory.repository.stopManualCreation(failed).getOrThrow()
        }
    }

    private fun showRoute(task: RecurringPaymentTask) {
        routeTask.value = task
        mounted.value = true
        if (!routeContent) {
            routeContent = true
            compose.setContent {
                CompositionLocalProvider(
                    LocalViewModelStoreOwner provides harness.models,
                    LocalRecurringPaymentOpenExpense provides { openedExpense.value = it },
                ) {
                    TicketboxTheme(skin = AppSkin.Default) {
                        val current = routeTask.value
                        if (mounted.value && current != null) {
                            RecurringPaymentRoute(
                                task = current,
                                factory = harness.screenFactory,
                                exit = ExpenseEditExitActions({ exited.value = true; mounted.value = false }, {}),
                                drafts = drafts,
                                admitted = { clientRef ->
                                    ManualExpenseSubmissionRoute(
                                        clientRef,
                                        harness.screenFactory,
                                        ExpenseEditExitActions({}, {}),
                                        related = ExpenseFactNavigation({}, { _, _ -> }),
                                    )
                                },
                            )
                        }
                    }
                }
            }
        }
        compose.waitForIdle()
    }

    private fun waitForSheet() {
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.ledger_manual_sheet_title))).fetchSemanticsNodes().isNotEmpty()
        }
    }

    private fun periodTask(recorded: String?, amount: Long?): RecurringPaymentTask {
        val binding = requireNotNull(harness.screenFactory.repository.captureDeferredLedgerBinding())
        return periodPaymentTask(binding, recorded, amount)
    }

    private fun readCreateRequest(payload: String) = readPeriodCreateRequest(payload)

    private fun augustUiState(task: RecurringPaymentTask) = RecurringOccurrenceUiState(
        access = LedgerAccessContext(task.binding, true),
        item = RecurringItem(
            publicId = task.seriesPublicId,
            ledgerId = task.binding.ledgerId,
            merchant = task.merchant,
            merchantKey = task.merchant,
            frequency = "monthly",
            baselineAmountCents = 1200,
            lastAmountCents = 1200,
            occurrenceCount = 0,
            lastSeenAt = null,
            nextExpectedDate = "2026-08-15",
            status = "active",
            confidence = null,
            source = "manual",
            anomalyStatus = "none",
            currentMonthAmountCents = null,
            historicalAverageAmountCents = null,
            amountDeltaPercent = null,
            createdAt = "2026-08-01T00:00:00Z",
            updatedAt = "2026-08-01T00:00:00Z",
            rowVersion = 7,
            pausedAt = null,
            archivedAt = null,
            nextDueDate = "2026-08-15",
            homeCurrencyCode = "JPY",
        ),
        occurrence = RecurringOccurrenceDto(
            seriesPublicId = task.seriesPublicId,
            period = task.period,
            seriesRowVersion = 7L,
            rowVersion = 3L,
            state = "unfulfilled",
            plannedAmountCents = 1200,
            reservedAmountCents = 1200,
            expensePublicId = null,
            paidAmountCents = null,
            nextDueDate = "2026-08-15",
            homeCurrencyCode = "JPY",
        ),
        ledgerHomeCurrencyCode = "CNY",
    )
}

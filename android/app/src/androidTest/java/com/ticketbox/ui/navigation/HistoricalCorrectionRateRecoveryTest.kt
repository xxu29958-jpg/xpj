package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.NavHostController
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.closeSoftKeyboard
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.*
import com.ticketbox.data.repository.*
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.ui.theme.TicketboxTheme
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import retrofit2.HttpException
import retrofit2.Response

/** Real outer/inner routes, repositories and one disk Room; only API responses are synthetic. */
class HistoricalCorrectionRateRecoveryTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val adapters = OutboxAdapterGraph()
    private var currentRate: ExchangeRateDto? = null
    private val correctionCalls = CopyOnWriteArrayList<Pair<ExpenseCorrectionRequestDto, String>>()
    private val rateCalls = CopyOnWriteArrayList<Pair<ExchangeRateRequestDto, String>>()
    private val providerCalls = CopyOnWriteArrayList<BudgetAdviseRequestDto>()
    private lateinit var sender: ApiService
    private val harness: FactEntryNavigationHarness = FactEntryNavigationHarness(context) { api ->
        object : ApiService by api {
            override suspend fun correctExpense(id: String, request: ExpenseCorrectionRequestDto,
                idempotencyKey: String?): ExpenseCorrectionResponseDto {
                correctionCalls += request to requireNotNull(idempotencyKey)
                if (request.expectedRowVersion != harness.fixture.network.current.rowVersion) {
                    throw refusal("state_conflict")
                }
                if (currentRate == null) throw refusal("exchange_rate_pending",
                    ",\"currency_code\":\"JPY\",\"home_currency_code\":\"CNY\",\"rate_date\":\"2025-12-03\"")
                val accepted = api.correctExpense(id, request, idempotencyKey)
                val corrected = accepted.expense.copy(originalCurrency = "JPY", originalCurrencyCode = "JPY",
                    originalAmountMinor = 12, homeCurrency = "CNY", amountCents = 60, homeAmountCents = 60)
                harness.fixture.network.current = corrected
                return accepted.copy(expense = corrected)
            }
            override suspend fun budgetAdviceInputs(month: String, timezone: String?, homeCurrencyCode: String?) =
                BudgetAdviceInputsDto(month, homeCurrencyCode ?: "CNY", DiscretionaryResponseDto(1000, 0, 0, 0, 0, 1000), emptyList())
            override suspend fun budgetAdvise(request: BudgetAdviseRequestDto): BudgetAdviseResponseDto {
                providerCalls += request
                error("Rate continuation must not generate advice")
            }
            override suspend fun exchangeRates(currencyCode: String?, homeCurrencyCode: String?, rateDate: String?, limit: Int) =
                ExchangeRateListDto(listOfNotNull(currentRate).filter { (currencyCode == null || it.currencyCode == currencyCode) &&
                    (homeCurrencyCode == null || it.homeCurrencyCode == homeCurrencyCode) && (rateDate == null || it.rateDate == rateDate) })
            override suspend fun saveExchangeRate(currencyCode: String, rateDate: String, request: ExchangeRateRequestDto,
                idempotencyKey: String): ExchangeRateDto {
                assertEquals("JPY", currencyCode)
                assertEquals("2025-12-03", rateDate)
                rateCalls += request to idempotencyKey
                return ExchangeRateDto("historical-rate", currencyCode, request.homeCurrencyCode, rateDate, request.rateToHome,
                    "manual", "2026-09-09T00:00:00Z", "2026-09-09T00:00:00Z", request.expectedRowVersion + 1).also { currentRate = it }
            }
        }.also { sender = it }
    }
    private val mounted = mutableStateOf(true)
    private lateinit var outer: NavHostController

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun factRateSaveReturnsToTheSameOriginalAndOnlyExplicitRetryCorrectsTheExpense() {
        val original = submitAndRefuse()
        installGraph()
        compose.runOnIdle { outer.openExpense(42) }
        openRate()
        enterRate()
        compose.onNodeWithTag("advice_rate_save").performScrollTo().performClick()
        compose.waitUntil(5_000) { harness.fixture.stored().size == 2 }
        val rateRow = harness.fixture.stored().single { it["type"] == "save_manual_exchange_rate" }
        val payload = requireNotNull(adapters.manualRateAdapter.fromJson(requireNotNull(rateRow["payload"])))
        assertEquals("2025-12", payload.month)
        assertEquals(ExchangeRateRequestDto("JPY", "CNY", "2025-12-03", "0.05", "manual", 0), payload.request)
        assertEquals(1, correctionCalls.size)
        assertTrue(rateCalls.isEmpty())
        assertEquals(1, runBlocking { drain().done })
        assertEquals("A rate receipt cannot send an expense correction", 1, correctionCalls.size)
        assertEquals(7L, harness.fixture.network.current.rowVersion)
        assertOriginal(original)
        backToOriginal()
        compose.onNodeWithText(context.getString(R.string.correction_rate_recheck)).performScrollTo().performClick()
        compose.waitUntil(5_000) { correctionRow()["status"] == "pending" }
        assertEquals(1, runBlocking { drain().done })
        assertEquals(correctionCalls.first(), correctionCalls.last())
        assertOriginal(original)
        assertEquals("done", correctionRow()["status"])
        assertEquals(12L, harness.fixture.network.current.originalAmountMinor)
        assertEquals(60L, harness.fixture.network.current.amountCents)
        assertTrue(providerCalls.isEmpty())
    }

    @Test fun bothGlobalEntrancesReachTheHistoricalPairAndBindingReplacementPreservesTheOriginal() {
        val original = submitAndRefuse()
        installGraph()
        compose.runOnIdle { harness.shell.openAccount() }
        val syncEntry = context.getString(R.string.settings_root_entry_offline_sync_title)
        waitForText(syncEntry)
        compose.onNodeWithText(syncEntry).performScrollTo().performClick()
        openRate()
        backToOriginal()
        assertOriginal(original)
        compose.runOnIdle { harness.shell.openSecondaryPage(ProductSecondaryPage.ObligationSync) }
        openRate()
        enterRate()
        harness.fixture.switchLedger()
        compose.waitUntil(5_000) { compose.onAllNodes(hasTestTag("advice_rate_value"), useUnmergedTree = true).fetchSemanticsNodes().isEmpty() }
        waitForText(context.getString(R.string.reports_binding_changed))
        compose.onNodeWithTag("advice_rate_save").assertDoesNotExist()
        assertEquals(original, correctionRow())
        assertEquals(1, correctionCalls.size)
        assertTrue(rateCalls.isEmpty())
        assertTrue(providerCalls.isEmpty())
    }

    @Test fun manualSubmissionRateRoundTripReturnsToItsOpenedFactAndExplicitOriginalRetry() {
        val ref = acceptedManualOriginal()
        val original = submitAndRefuse()
        installGraph()
        openManualFact(ref)
        openRate()
        enterRate()
        compose.onNodeWithTag("advice_rate_save").performScrollTo().performClick()
        compose.waitUntil(5_000) { harness.fixture.stored().any { it["type"] == "save_manual_exchange_rate" } }
        assertEquals(1, runBlocking { drain().done })
        backToOriginal()
        assertEquals(1, correctionCalls.size)
        assertEquals(7L, harness.fixture.network.current.rowVersion)
        assertOriginal(original)
        compose.onNodeWithText(context.getString(R.string.correction_rate_recheck)).performScrollTo().performClick()
        compose.waitUntil(5_000) { correctionRow()["status"] == "pending" }
        assertEquals(1, runBlocking { drain().done })
        assertEquals(correctionCalls.first(), correctionCalls.last())
        assertEquals("done", correctionRow()["status"])
        assertOriginal(original)
        assertTrue(providerCalls.isEmpty())
    }

    @Test fun manualSubmissionDoesNotRestoreItsOpenedFactUnderAReplacementBinding() {
        val ref = acceptedManualOriginal()
        val original = submitAndRefuse()
        installGraph()
        openManualFact(ref)
        openRate()
        harness.fixture.switchLedger()
        waitForText(context.getString(R.string.reports_binding_changed))
        val factReads = harness.fixture.network.expenseReads.toList()
        compose.onNodeWithContentDescription(context.getString(R.string.correction_rate_back)).performScrollTo().performClick()
        waitForText(context.getString(R.string.manual_submission_missing))
        compose.onNodeWithText(context.getString(R.string.correction_rate_recheck)).assertDoesNotExist()
        assertEquals(factReads, harness.fixture.network.expenseReads.toList())
        assertEquals(original, correctionRow())
        assertTrue(rateCalls.isEmpty())
        assertTrue(providerCalls.isEmpty())
    }

    @Test fun reopenedRoomKeepsTheRefusalAndChangedFactStillConflictsWithTheOriginalToken() = runBlocking {
        val original = submitAndRefuse()
        val graph = harness.fixture.reopen()
        val pending = graph.expenseRepository.observeCorrections().first().corrections.single()
        assertEquals("2025-12-03", pending.missingExchangeRate?.rateDate)
        assertEquals(original, correctionRow())
        harness.fixture.network.current = harness.fixture.network.current.copy(rowVersion = 8)
        val binding = requireNotNull(graph.expenseRepository.captureDeferredLedgerBinding())
        graph.expenseRepository.recoverCorrection(binding, pending.row.id, drop = false).getOrThrow()
        assertEquals(1, drain().conflicts)
        assertEquals("conflict", correctionRow()["status"])
        assertOriginal(original)
        assertEquals(correctionCalls.first(), correctionCalls.last())
        assertTrue(rateCalls.isEmpty())
        assertTrue(providerCalls.isEmpty())
    }

    private fun submitAndRefuse(): Map<String, String?> = runBlocking {
        harness.fixture.network.loseResponse = false
        val repository = harness.fixture.graph.expenseRepository
        val binding = requireNotNull(repository.captureDeferredLedgerBinding())
        repository.submitCorrection(binding, harness.fixture.network.current.toDomain(),
            ExpenseCorrectionDraft("这笔原来是日元 12", originalCurrencyCode = CurrencyCode.JPY, originalAmountMinor = 12)).getOrThrow()
        assertEquals(1, drain().failures)
        assertEquals(7L, harness.fixture.network.current.rowVersion)
        correctionRow()
    }

    private fun correctionRow() = harness.fixture.stored().single { it["type"] == "correct_expense" }

    private fun acceptedManualOriginal(): String = runBlocking {
        val original = harness.fixture.network.current
        val local = harness.screenFactory.repository.createManualExpense(ExpenseDraft(amountCents = 1000,
            originalCurrencyCode = CurrencyCode.CNY, originalAmountMinor = 1000, ledgerHomeCurrency = CurrencyCode.CNY,
            merchant = original.merchant, category = original.category, note = null, expenseTime = null,
            tags = null, valueScore = null, regretScore = null)).getOrThrow()
        val row = harness.fixture.outbox.observeActiveByTypes(setOf(PendingMutationType.CreateExpense)).first().single()
        val ref = requireNotNull(local.clientRef)
        // This accepted original precedes the already corrected canonical row (version 7).
        harness.fixture.expenseDao.applyLocalCreateServerIdentity(row.ledgerId,
            original.toEntity(row.ledgerId).copy(clientRef = ref))
        assertTrue(harness.fixture.outbox.tryClaim(row.id))
        harness.fixture.outbox.markDone(row.id, receiptJson = expenseAcceptanceReceiptJson(original.id))
        ref
    }

    private fun openManualFact(ref: String) {
        compose.runOnIdle { outer.navigate(manualExpenseSubmissionRoute(ref)) }
        val open = context.getString(R.string.manual_submission_open)
        waitForText(open)
        compose.onNodeWithText(open).performScrollTo().performClick()
        waitForText(context.getString(R.string.correction_rate_recheck))
    }

    private fun assertOriginal(original: Map<String, String?>) {
        val retained = correctionRow()
        for (column in listOf("id", "payload", "idempotencyKey", "expectedRowVersion", "ownerKey", "ledgerId", "serverUrl")) {
            assertEquals(column, original[column], retained[column])
        }
    }

    private suspend fun drain() = OutboxDrainEngine(harness.fixture.outbox, listOf(
        CorrectExpenseDispatcher({ sender }, adapters.correctionAdapter,
            { row, expense -> harness.fixture.graph.expenseRepository.publishDeliveredCorrection(row, expense) }, {}),
        ManualExchangeRateDispatcher({ sender }, adapters.manualRateAdapter, adapters.manualRateReceiptAdapter)),
        maxAttempts = 1, now = harness.fixture.clock::millis).drainOnce()

    private fun openRate() {
        val text = context.getString(R.string.correction_rate_open)
        waitForText(text)
        compose.onNodeWithText(text).performScrollTo().performClick()
        compose.waitUntil(5_000) { compose.onAllNodes(hasTestTag("advice_rate_value"), useUnmergedTree = true).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText(context.getString(R.string.advice_rate_pair_date, "JPY", "CNY", "2025-12-03"))
            .performScrollTo().assertIsDisplayed()
    }

    private fun enterRate() {
        val field = compose.onNode(hasSetTextAction() and hasAnyAncestor(hasTestTag("advice_rate_value")), useUnmergedTree = true)
        field.performScrollTo().performTextReplacement("0.05")
        field.assertTextEquals("0.05")
        closeSoftKeyboard()
        compose.waitForIdle()
    }

    private fun backToOriginal() {
        compose.onNodeWithContentDescription(context.getString(R.string.correction_rate_back)).performScrollTo().performClick()
        waitForText(context.getString(R.string.correction_rate_recheck))
    }

    private fun waitForText(text: String) {
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(text)).fetchSemanticsNodes().isNotEmpty() }
    }

    private fun installGraph() {
        compose.setContent { if (mounted.value) {
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) { TicketboxTheme(skin = AppSkin.Default) {
                val nav = rememberNavController()
                outer = nav
                MainNavGraph(MainNavigationRuntime(nav, harness.shell, harness.screenFactory), remember { SnackbarHostState() },
                    SettingsPreferenceControls(AppSkin.Default, AppThemeMode.System, CurrencyCode.CNY, {}, {}), {})
            } }
        } }
        compose.waitForIdle()
    }

    private fun refusal(code: String, details: String = "") = HttpException(Response.error<Any>(409,
        "{\"error\":\"$code\",\"message\":\"需要处理原提交\"$details}".toResponseBody("application/json".toMediaType())))
}

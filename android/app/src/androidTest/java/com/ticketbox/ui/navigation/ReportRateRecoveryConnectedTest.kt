package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performImeAction
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.dto.ExchangeRateRequestDto
import com.ticketbox.data.repository.LedgerRequestGuard
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.theme.TicketboxTheme
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Reports retain their month while repairing a different period's FX through the existing owner. */
class ReportRateRecoveryConnectedTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val fixture = BudgetAdviceManualRateFixture(context)
    private val mounted = mutableStateOf(true)
    private val models = object : ViewModelStoreOwner { override val viewModelStore = ViewModelStore() }
    private val report = ReportRateContext(fixture.binding, "2026-09", "JPY", "CNY", "2026-08-05")
    private val request = ExchangeRateRequestDto("CNY", "JPY", "2026-08-05", "20", "manual", 0)

    @After fun close() {
        compose.runOnIdle { mounted.value = false; models.viewModelStore.clear() }
        compose.waitForIdle()
        fixture.close()
    }

    @Test fun historicalReportGapEntersTheRateOwnerAndSavesTheOriginalTaskWithoutGeneratingAdvice() {
        fixture.runtimeHome = "CNY"
        show()
        waitForEditor()
        compose.waitUntil(5_000) { fixture.inputReads.lastOrNull() == (report.month to report.homeCurrencyCode) }
        // The budget inputs fixture offers its own month's day 07. The report's day 05
        // must enter directly; searching only the current input gaps cannot find it.
        assertTrue(fixture.rateDate != report.rateDate)
        enterRate("20")
        compose.onNodeWithTag("advice_rate_save").performScrollTo().assertIsDisplayed().assertIsEnabled().performClick()
        val original = fixture.awaitSavedRow(compose)
        val intent = requireNotNull(fixture.adapters.manualRateAdapter.fromJson(original.payload))
        assertEquals(report.month, intent.month)
        assertEquals(request, intent.request)
        assertEquals(0L, original.expectedRowVersion)
        assertTrue(fixture.writes.isEmpty())
        assertTrue(fixture.adviceCalls.isEmpty())
        val readsBefore = fixture.inputReads.size
        assertEquals(1, runBlocking { fixture.drain().done })
        compose.waitUntil(5_000) { fixture.inputReads.size > readsBefore }
        val accepted = runBlocking { fixture.pending(original.id) }
        assertTrue(accepted.isConfirmed)
        assertEquals(PendingMutationStatus.Done, accepted.row.status)
        assertEquals(original.payload, accepted.row.payloadJson)
        assertEquals(original.idempotencyKey, accepted.row.idempotencyKey)
        assertEquals(request, fixture.writes.single().first)
        assertEquals(original.idempotencyKey, fixture.writes.single().second)
        assertEquals(report.rateDate, accepted.receipt?.rateDate)
        assertEquals(report.homeCurrencyCode, accepted.receipt?.homeCurrencyCode)
        assertEquals(report.month to report.homeCurrencyCode, fixture.inputReads.last())
        assertTrue(fixture.adviceCalls.isEmpty())
    }

    @Test fun bindingReplacementRejectsTheOriginalReportContextAndPreservesTheQueuedBytes() {
        val id = runBlocking {
            fixture.repository.enqueueRate(fixture.binding, report.month, request, null).getOrThrow()
        }
        runBlocking { fixture.outbox.markFailed(id, "client_upgrade_required") }
        val original = runBlocking { fixture.rows().single() }
        show()
        waitForEditor()
        enterRate("21")
        fixture.switchBinding()
        compose.waitUntil(5_000) {
            compose.onAllNodes(hasTestTag("advice_rate_value"), useUnmergedTree = true).fetchSemanticsNodes().isEmpty()
        }
        compose.waitUntil(5_000) {
            compose.onAllNodes(hasText(context.getString(R.string.reports_binding_changed))).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithTag("advice_rate_save").assertDoesNotExist()
        val staleSave = runBlocking {
            fixture.repository.enqueueRate(report.binding, report.month, request.copy(rateToHome = "21"), null)
        }
        assertEquals(LedgerRequestGuard.LEDGER_CHANGED_MESSAGE, staleSave.exceptionOrNull()?.message)
        val retained = runBlocking { fixture.rows().single() }
        assertEquals(original, retained)
        assertTrue(fixture.writes.isEmpty())
        assertTrue(fixture.adviceCalls.isEmpty())
    }

    private fun show() {
        val factory = fixture.screenFactory
        compose.setContent { if (mounted.value) TicketboxTheme(skin = AppSkin.Default) {
            CompositionLocalProvider(LocalViewModelStoreOwner provides models,
                LocalCurrencyDisplay provides CurrencyDisplay(CurrencyCode.CNY)) {
                BudgetAdviceRoute(factory, onBack = {}, reportContext = report)
            }
        } }
    }

    private fun waitForEditor() {
        compose.waitUntil(5_000) {
            compose.onAllNodes(hasTestTag("advice_rate_value"), useUnmergedTree = true).fetchSemanticsNodes().isNotEmpty()
        }
    }

    private fun enterRate(value: String) {
        val rateInput = compose.onNode(hasSetTextAction() and hasAnyAncestor(hasTestTag("advice_rate_value")), useUnmergedTree = true)
        rateInput.performScrollTo().performTextReplacement(value)
        rateInput.assertTextEquals(value).performImeAction()
    }
}

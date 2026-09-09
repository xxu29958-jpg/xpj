package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
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

/** Real Route -> ViewModel -> repository -> Room -> dispatcher, with controlled remote ACK loss. */
class BudgetAdviceManualRateRecoveryTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val fixture = BudgetAdviceManualRateFixture(context)
    private val mounted = mutableStateOf(true)
    private val models = object : ViewModelStoreOwner { override val viewModelStore = ViewModelStore() }

    @After fun close() {
        compose.runOnIdle { mounted.value = false; models.viewModelStore.clear() }
        compose.waitForIdle()
        fixture.close()
    }

    @Test fun savingAMissingRateFromTheRouteOnlyRecalculatesUntilExplicitGeneration() {
        show()
        waitForText(context.getString(R.string.advice_rate_add))
        compose.onNodeWithText("‹").performScrollTo().performClick()
        compose.waitUntil(5_000) { fixture.inputReads.lastOrNull()?.first == fixture.originalMonth }
        compose.onNodeWithText(context.getString(R.string.advice_rate_add)).performScrollTo().performClick()
        compose.waitUntil(5_000) { compose.onAllNodes(hasTestTag("advice_rate_value"), useUnmergedTree = true)
            .fetchSemanticsNodes().isNotEmpty() }
        compose.onNode(hasSetTextAction() and hasAnyAncestor(hasTestTag("advice_rate_value")), useUnmergedTree = true)
            .performScrollTo().performTextReplacement("20")
        compose.onNodeWithTag("advice_rate_save").performScrollTo().performClick()
        compose.waitUntil(5_000) { runBlocking { fixture.rows().size == 1 } }
        val row = runBlocking { fixture.rows().single() }
        val intent = requireNotNull(fixture.adapters.manualRateAdapter.fromJson(row.payload))
        assertEquals(fixture.originalMonth, intent.month)
        assertEquals(fixture.request, intent.request)
        assertEquals(0L, row.expectedRowVersion)
        assertTrue(fixture.writes.isEmpty())
        val readsBefore = fixture.inputReads.size
        assertEquals(1, runBlocking { fixture.drain().done })
        compose.waitUntil(5_000) { fixture.inputReads.size > readsBefore }
        waitForText(context.getString(R.string.budget_advice_generate))
        assertTrue(fixture.adviceCalls.isEmpty())
        assertEquals(fixture.originalMonth to "JPY", fixture.inputReads.last())
        compose.onNodeWithText(context.getString(R.string.budget_advice_generate)).performScrollTo().performClick()
        compose.waitUntil(5_000) { fixture.adviceCalls.size == 1 }
        assertEquals(fixture.originalMonth, fixture.adviceCalls.single().month)
        assertEquals("JPY", fixture.adviceCalls.single().homeCurrencyCode)
    }

    @Test fun originalRouteReopensRoomAndReplaysOriginalReceiptWithoutOverwritingLaterCanonicalRate() {
        val id = runBlocking { fixture.repository.enqueueRate(fixture.binding, fixture.originalMonth, fixture.request, null).getOrThrow() }
        val original = runBlocking { fixture.rows().single() }
        fixture.loseAck = true
        assertEquals(1, runBlocking { fixture.drain().failures })
        fixture.latest = requireNotNull(fixture.latest).copy(rateToHome = "25", rowVersion = 2)
        fixture.runtimeHome = "CNY"
        fixture.reopen()
        assertEquals(original.payload, runBlocking { fixture.rows().single().payload })
        show(id)
        waitForText(context.getString(R.string.advice_rate_original_month, fixture.originalMonth))
        compose.onNodeWithText(context.getString(R.string.advice_rate_original_value, "CNY", "20", "JPY"))
            .performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.advice_rate_retry)).performScrollTo().performClick()
        compose.waitUntil(5_000) { runBlocking { fixture.pending(id).row.status == PendingMutationStatus.Pending } }
        fixture.loseAck = false
        val readsBefore = fixture.inputReads.size
        assertEquals(1, runBlocking { fixture.drain().done })
        compose.waitUntil(5_000) { fixture.inputReads.size > readsBefore }
        waitForText(context.getString(R.string.advice_rate_submission_done))
        val accepted = runBlocking { fixture.pending(id) }
        assertEquals("20", accepted.receipt?.rateToHome)
        assertEquals(1L, accepted.receipt?.rowVersion)
        assertEquals("25", fixture.latest?.rateToHome)
        assertEquals(2L, fixture.latest?.rowVersion)
        assertEquals(original.payload, accepted.row.payloadJson)
        assertEquals(original.expectedRowVersion, accepted.row.expectedRowVersion)
        assertEquals(listOf(original.idempotencyKey, original.idempotencyKey), fixture.writes.map { it.second })
        assertEquals(listOf(fixture.request, fixture.request), fixture.writes.map { it.first })
        assertEquals(fixture.originalMonth to "JPY", fixture.inputReads.last())
        assertTrue(fixture.adviceCalls.isEmpty())
        compose.onNodeWithText(context.getString(R.string.advice_rate_current, "25", 2L))
            .performScrollTo().assertIsDisplayed()
    }

    @Test fun bindingReplacementClosesRateEditorAndStopConfirmationWithoutChangingOriginalSubmission() {
        val id = runBlocking { fixture.repository.enqueueRate(fixture.binding, fixture.originalMonth, fixture.request, null).getOrThrow() }
        runBlocking { fixture.outbox.markFailed(id, "client_upgrade_required") }
        val original = runBlocking { fixture.rows().single() }
        show(id)
        waitForText(context.getString(R.string.advice_rate_original_month, fixture.originalMonth))
        compose.onNodeWithText(context.getString(R.string.advice_rate_review_current)).performScrollTo().performClick()
        compose.waitUntil(5_000) { compose.onAllNodes(hasTestTag("advice_rate_value"), useUnmergedTree = true)
            .fetchSemanticsNodes().isNotEmpty() }
        compose.onNode(hasSetTextAction() and hasAnyAncestor(hasTestTag("advice_rate_value")), useUnmergedTree = true)
            .performScrollTo().performTextReplacement("21")
        compose.onNodeWithText(context.getString(R.string.advice_rate_stop)).performScrollTo().performClick()
        val stopBody = context.getString(R.string.advice_rate_stop_body)
        waitForText(stopBody)
        fixture.switchBinding()
        compose.waitUntil(5_000) { compose.onAllNodes(hasTestTag("advice_rate_value"), useUnmergedTree = true)
            .fetchSemanticsNodes().isEmpty() }
        compose.onNodeWithText(stopBody).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.advice_rate_original_month, fixture.originalMonth)).assertDoesNotExist()
        compose.onNodeWithTag("advice_rate_save").assertDoesNotExist()
        val staleSave = runBlocking { fixture.repository.enqueueRate(fixture.binding, fixture.originalMonth, fixture.request, null) }
        assertEquals(LedgerRequestGuard.LEDGER_CHANGED_MESSAGE, staleSave.exceptionOrNull()?.message)
        val retained = runBlocking { fixture.rows().single() }
        assertEquals(original.id, retained.id)
        assertEquals(original.payload, retained.payload)
        assertEquals(original.idempotencyKey, retained.idempotencyKey)
        assertEquals(original.expectedRowVersion, retained.expectedRowVersion)
        assertEquals(original.status, retained.status)
        assertTrue(fixture.writes.isEmpty())
        assertTrue(fixture.adviceCalls.isEmpty())
    }

    private fun show(originalSubmissionId: Long? = null) {
        val factory = fixture.screenFactory
        compose.setContent { if (mounted.value) TicketboxTheme(skin = AppSkin.Default) {
            CompositionLocalProvider(LocalViewModelStoreOwner provides models,
                LocalCurrencyDisplay provides CurrencyDisplay(CurrencyCode.CNY)) {
                BudgetAdviceRoute(factory, onBack = {}, originalSubmissionId = originalSubmissionId)
            }
        } }
    }

    private fun waitForText(text: String) {
        compose.waitUntil(5_000) { compose.onAllNodes(androidx.compose.ui.test.hasText(text))
            .fetchSemanticsNodes().isNotEmpty() }
    }
}

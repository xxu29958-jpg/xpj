package com.ticketbox.ui.navigation

import android.content.Context
import android.view.WindowManager
import androidx.activity.ComponentActivity
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.closeSoftKeyboard
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.data.remote.dto.ExchangeRateDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.RealKeyboard
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

/** Actual route, VM, repository, Room and dispatcher; only the remote service is synthetic. */
class MonthlyArrangementRouteTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()
    @get:Rule val keyboard = RealKeyboard()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val fixture = BudgetAdviceManualRateFixture(context)
    private val mounted = mutableStateOf(true)
    private val models = object : ViewModelStoreOwner { override val viewModelStore = ViewModelStore() }

    @After fun close() {
        compose.runOnIdle { mounted.value = false; models.viewModelStore.clear() }
        compose.waitForIdle()
        fixture.close()
    }

    @Test fun trialIsNotSavedAndExplicitSaveSurvivesReopenAlongsideANewerDraft() {
        fixture.latest = ExchangeRateDto("rate", "CNY", "JPY", fixture.rateDate, "20", "manual",
            "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z", 1)
        show()
        waitForInput()
        capture("arrangement-entry")
        edit("arrangement_savings", "3000")
        edit("arrangement_buffer", "500")
        tap("arrangement_trial")
        assertTextDisplayed(context.getString(R.string.arrangement_trial_basis))
        assertNull(fixture.arrangement)
        assertTrue(runBlocking { fixture.rows().isEmpty() })
        tap("arrangement_save")
        val row = fixture.awaitSavedRow(compose)
        val intent = requireNotNull(fixture.adapters.arrangementSaveAdapter.fromJson(row.payload))
        assertEquals("JPY", intent.request.homeCurrencyCode)
        assertEquals(3000L, intent.request.savingsTargetCents)
        assertEquals(500L, intent.request.reservedBufferCents)
        assertEquals(0L, row.expectedRowVersion)
        assertNull(fixture.arrangement)
        assertEquals(1, runBlocking { fixture.drain().done })
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(context.getString(R.string.arrangement_confirmed))).fetchSemanticsNodes().isNotEmpty() }
        assertEquals(3000L, fixture.arrangement?.savingsTargetCents)
        compose.onNodeWithText(context.getString(R.string.arrangement_history)).performScrollTo().performClick()
        assertTextDisplayed(context.getString(R.string.arrangement_history_revision, 1L))
        androidx.test.espresso.Espresso.pressBack()
        edit("arrangement_savings", "8000")
        tap("arrangement_trial")
        val shortfall = context.getString(R.string.arrangement_shortfall,
            formatDisplayAmount(1500L, CurrencyDisplay.forRecord("JPY")))
        assertTextDisplayed(shortfall)
        capture("arrangement-trial")
        assertEquals(3000L, fixture.arrangement?.savingsTargetCents)
        compose.runOnIdle { mounted.value = false; models.viewModelStore.clear() }
        compose.waitForIdle()
        fixture.reopen()
        compose.runOnIdle { mounted.value = true }
        waitForInput()
        input("arrangement_savings").performScrollTo().assertTextEquals("8000")
        assertEquals(3000L, fixture.arrangement?.savingsTargetCents)
        assertEquals(1, fixture.arrangementWrites.size)
        tap("arrangement_save")
        compose.waitUntil(5_000) { runBlocking { fixture.rows().size == 2 } }
        val next = runBlocking { fixture.rows().single { it.id != row.id } }
        assertEquals(1L, next.expectedRowVersion)
        assertNotEquals(row.idempotencyKey, next.idempotencyKey)
        assertEquals(1, runBlocking { fixture.drain().done })
        assertEquals(8000L, fixture.arrangement?.savingsTargetCents)
        assertEquals(2L, fixture.arrangement?.rowVersion)
        assertEquals(2, fixture.arrangementWrites.size)
        assertTrue(fixture.adviceCalls.isEmpty())
        val receiptsBeforeRead = runBlocking { fixture.rows() }
        fixture.historyUnavailable = true
        fixture.historyReadGate = kotlinx.coroutines.CompletableDeferred()
        compose.onNodeWithText(context.getString(R.string.arrangement_history)).performScrollTo().performClick()
        assertTextDisplayed(context.getString(R.string.budget_history_loading))
        compose.waitForIdle()
        fixture.historyReadGate?.complete(Unit)
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(context.getString(R.string.arrangement_history_revision, 2L))).fetchSemanticsNodes().isNotEmpty() }
        captureHistory("arrangement-history-after-load")
        assertHistoryReachable(context.getString(R.string.arrangement_history_revision, 1L))
        assertTextDisplayed(context.getString(R.string.arrangement_history_revision, 2L))
        assertTextDisplayed("JPY ¥8,000")
        assertTextDisplayed(context.getString(R.string.arrangement_history_receipt_source))
        captureHistory("arrangement-history-latest")
        compose.onAllNodesWithText("JPY ¥3,000")[0].performScrollTo().assertIsDisplayed()
        compose.onAllNodesWithText("查看当时定义")[0].performScrollTo().performClick()
        assertTextDisplayed("备用金 · JPY ¥500")
        assertTextDisplayed(context.getString(R.string.arrangement_history_revision, 1L))
        captureHistory("arrangement-history-earlier")
        androidx.test.espresso.Espresso.pressBack()
        compose.onNodeWithTag("arrangement-history").assertDoesNotExist()
        input("arrangement_savings").performScrollTo().assertTextEquals("8000")
        assertEquals(8000L, fixture.arrangement?.savingsTargetCents)
        assertEquals(2, fixture.arrangementWrites.size)
        fixture.historyUnavailable = false
        compose.onNodeWithText(context.getString(R.string.arrangement_history)).performScrollTo().performClick()
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(context.getString(R.string.plan_history_query_receipt))).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText(context.getString(R.string.arrangement_history_receipt_source)).assertDoesNotExist()
        captureHistory("arrangement-history-refreshed")
        androidx.test.espresso.Espresso.pressBack()
        input("arrangement_savings").performScrollTo().assertTextEquals("8000")
        assertEquals(receiptsBeforeRead, runBlocking { fixture.rows() })
    }

    private fun show() {
        // Match MainActivity's manifest: an unspecified test window can pan the
        // already IME-inset page a second time when a text field gains focus.
        compose.runOnUiThread { compose.activity.window.setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE) }
        val skin = if (InstrumentationRegistry.getArguments().getString("captureSkin") == "midnight") AppSkin.Midnight else AppSkin.Paper
        compose.setContent { if (mounted.value) TicketboxTheme(skin = skin) {
            CompositionLocalProvider(LocalViewModelStoreOwner provides models,
                LocalCurrencyDisplay provides CurrencyDisplay(CurrencyCode.CNY)) {
                BudgetAdviceRoute(fixture.screenFactory, onBack = {})
            }
        } }
    }
    private fun waitForInput() {
        compose.waitUntil(5_000) { compose.onAllNodes(hasSetTextAction() and hasAnyAncestor(hasTestTag("arrangement_savings")) and isEnabled(), useUnmergedTree = true)
            .fetchSemanticsNodes().isNotEmpty() }
        compose.waitForIdle()
    }
    private fun input(tag: String) = compose.onNode(hasSetTextAction() and hasAnyAncestor(hasTestTag(tag)), useUnmergedTree = true)
    private fun assertTextDisplayed(text: String) {
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(text)).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText(text).performScrollTo().assertIsDisplayed()
    }
    private fun assertHistoryReachable(text: String) {
        repeat(8) {
            if (compose.onNodeWithText(text).isDisplayed()) return
            compose.onNodeWithTag("arrangement-history").performTouchInput { swipeUp() }
            compose.waitForIdle()
        }
        compose.onNodeWithText(text).assertIsDisplayed()
    }
    private fun edit(tag: String, value: String) {
        waitForInput()
        input(tag).performScrollTo().performTextReplacement(value)
        closeSoftKeyboard()
        compose.waitForIdle()
    }
    private fun tap(tag: String) {
        if (tag == "arrangement_save") {
            input("arrangement_savings").performScrollTo().performClick()
            keyboard.assertActionAboveKeyboard(compose, context.getString(R.string.arrangement_save), "arrangement-save-keyboard")
        } else compose.onNodeWithTag(tag).performScrollTo()
        compose.onNodeWithTag(tag).assertIsDisplayed().assertIsEnabled().performClick()
        keyboard.dismissAndWait(compose)
    }
    private fun capture(name: String) {
        saveConsumerArtPreview(name, compose.onRoot().captureToImage().asAndroidBitmap())
    }
    private fun captureHistory(name: String) {
        saveConsumerArtPreview(name, compose.onNodeWithTag("arrangement-history").captureToImage().asAndroidBitmap())
    }
}

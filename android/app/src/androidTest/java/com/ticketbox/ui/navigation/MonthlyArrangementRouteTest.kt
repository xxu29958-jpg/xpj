package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.closeSoftKeyboard
import com.ticketbox.R
import com.ticketbox.data.remote.dto.ExchangeRateDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.theme.TicketboxTheme
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

/** Actual route, VM, repository, Room and dispatcher; only the remote service is synthetic. */
class MonthlyArrangementRouteTest {
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

    @Test fun trialIsNotSavedAndExplicitSaveSurvivesReopenAlongsideANewerDraft() {
        fixture.latest = ExchangeRateDto("rate", "CNY", "JPY", fixture.rateDate, "20", "manual",
            "2026-09-01T00:00:00Z", "2026-09-01T00:00:00Z", 1)
        show()
        waitForInput()
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
        edit("arrangement_savings", "8000")
        tap("arrangement_trial")
        val shortfall = context.getString(R.string.arrangement_shortfall,
            formatDisplayAmount(1500L, CurrencyDisplay.forRecord("JPY")))
        assertTextDisplayed(shortfall)
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
    }

    private fun show() {
        compose.setContent { if (mounted.value) TicketboxTheme(skin = AppSkin.Default) {
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
    private fun edit(tag: String, value: String) {
        waitForInput()
        input(tag).performScrollTo().performTextReplacement(value)
        closeSoftKeyboard()
        compose.waitForIdle()
    }
    private fun tap(tag: String) { compose.onNodeWithTag(tag).performScrollTo().assertIsEnabled().performClick(); compose.waitForIdle() }
}

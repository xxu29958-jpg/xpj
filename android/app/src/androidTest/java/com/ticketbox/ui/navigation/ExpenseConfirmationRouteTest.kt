package com.ticketbox.ui.navigation

import android.content.Context
import androidx.activity.ComponentActivity
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.withConfirmationReceipt
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Production editor, Graph, disk Outbox and fact route; only transport/session are controlled. */
class ExpenseConfirmationRouteTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val mounted = mutableStateOf(true)
    private lateinit var harness: FactEntryNavigationHarness
    private var exits = 0

    @After fun close() {
        compose.runOnIdle { mounted.value = false; compose.activity.viewModelStore.clear() }
        compose.waitForIdle()
        if (::harness.isInitialized) harness.close()
    }

    @Test fun acceptedConfirmationStaysOnItsFirstReceiptBeforeOpeningTheLaterFact() {
        harness = FactEntryNavigationHarness(context)
        val network = harness.fixture.network
        network.current = network.current.copy(status = "pending", confirmedAt = null,
            merchant = "首次便利店", amountCents = 12860, originalAmountMinor = 12860, category = "购物")
        network.patchReply = network.current.copy(rowVersion = 8)
        val accepted = network.current.copy(status = "confirmed", rowVersion = 9,
            confirmedAt = "2026-09-07T00:00:00Z").withConfirmationReceipt()
        network.confirmReply = accepted.copy(merchant = "后来更正的商家", amountCents = 9900L,
            originalAmountMinor = 9900L, rowVersion = 10, factRevision = 4)
        compose.setContent {
            val dark = InstrumentationRegistry.getArguments().getString("receiptTheme") == "midnight"
            CompositionLocalProvider(LocalViewModelStoreOwner provides compose.activity) {
                TicketboxTheme(skin = if (dark) AppSkin.Midnight else AppSkin.Paper) {
                    if (mounted.value) ExpenseEditRoute(42, harness.screenFactory, ExpenseEditExitActions(
                        { exits++ }, { changed -> assertTrue(changed); exits++ }), ExpenseFactNavigation({}, { _, _ -> }))
                }
            }
        }
        waitFor("确认入账")
        compose.onNodeWithText("确认入账").performClick()
        compose.waitUntil(10_000) { runBlocking { harness.fixture.stored().isNotEmpty() } }
        assertEquals(0, exits)
        runBlocking { harness.fixture.drainExpenseLifecycle(maxAttempts = 4) }
        network.current = requireNotNull(network.confirmReply).copy(confirmationReceipt = null)
        val commands = harness.fixture.stored()
        assertEquals("42", network.patchCalls.single().first)
        assertEquals(7L, network.patchCalls.single().second.expectedRowVersion)
        assertEquals(commands.single { it["type"] == PendingMutationType.PatchExpense.wireValue }["idempotencyKey"],
            network.patchCalls.single().third)
        assertEquals("42", network.confirmCalls.single().first)
        assertEquals(8L, network.confirmCalls.single().second.expectedRowVersion)
        assertEquals(commands.single { it["type"] == PendingMutationType.ConfirmExpense.wireValue }["idempotencyKey"],
            network.confirmCalls.single().third)
        compose.waitUntil(10_000) { exits > 0 || compose.onAllNodes(hasText("这张，记好了")).fetchSemanticsNodes().isNotEmpty() }
        assertEquals("Acceptance must stay visible until the user chooses where to go", 0, exits)
        waitFor("首次便利店 · 家庭账本")
        waitFor("¥128.60")
        capture("confirmation-first-receipt")
        compose.onNodeWithText("查看这笔账单").performScrollTo()
        capture("confirmation-receipt-actions")
        compose.onNodeWithText("查看这笔账单").performClick()
        waitFor("后来更正的商家")
        androidx.test.espresso.Espresso.pressBack()
        waitFor("这张，记好了")
        waitFor("¥128.60")
        compose.onNodeWithText("完成并返回").performClick()
        compose.waitUntil(5_000) { exits == 1 }
        assertEquals("The later current fact is never replaced by its first receipt", "后来更正的商家", harness.fixture.network.current.merchant)
    }

    private fun waitFor(text: String) = compose.waitUntil(10_000) {
        compose.onAllNodes(hasText(text)).fetchSemanticsNodes().isNotEmpty()
    }

    private fun capture(name: String) {
        compose.waitForIdle()
        InstrumentationRegistry.getInstrumentation().uiAutomation.waitForIdle(250, 5_000)
        saveConsumerArtPreview(name, InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot())
    }
}

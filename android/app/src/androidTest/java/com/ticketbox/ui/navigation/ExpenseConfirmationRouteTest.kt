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
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.repository.ConfirmExpenseDispatcher
import com.ticketbox.data.repository.OutboxDrainEngine
import com.ticketbox.data.repository.PatchExpenseDispatcher
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
    private lateinit var api: ApiService
    private var exits = 0

    @After fun close() {
        compose.runOnIdle { mounted.value = false; compose.activity.viewModelStore.clear() }
        compose.waitForIdle()
        if (::harness.isInitialized) harness.close()
    }

    @Test fun acceptedConfirmationStaysOnItsFirstReceiptBeforeOpeningTheLaterFact() {
        harness = FactEntryNavigationHarness(context) { original ->
            object : ApiService by original {
                override suspend fun confirmExpense(id: String, request: ExpenseStateTokenRequest, idempotencyKey: String?): ExpenseDto {
                    val accepted = original.confirmExpense(id, request, idempotencyKey).withConfirmationReceipt()
                    val current = accepted.copy(merchant = "后来更正的商家", amountCents = 9900L, originalAmountMinor = 9900L,
                        rowVersion = accepted.rowVersion + 1, factRevision = accepted.factRevision + 1, confirmationReceipt = null)
                    harness.fixture.network.current = current
                    return current.copy(confirmationReceipt = accepted.confirmationReceipt)
                }
            }.also { api = it }
        }
        harness.fixture.network.current = harness.fixture.network.current.copy(status = "pending", confirmedAt = null,
            merchant = "首次便利店", amountCents = 12860, originalAmountMinor = 12860, category = "购物")
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
        drain()
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

    private fun drain() = runBlocking {
        val graph = OutboxAdapterGraph()
        val publish: suspend (String, ExpenseDto) -> Unit = { ledger, expense ->
            harness.fixture.publishExpense(ledger, expense)
        }
        OutboxDrainEngine(harness.fixture.outbox, listOf(
            PatchExpenseDispatcher({ api }, graph.patchExpenseAdapter, publish),
            ConfirmExpenseDispatcher({ api }, graph.expenseStateTokenAdapter, publish),
        ), maxAttempts = 4, now = harness.fixture.clock::millis).drainOnce()
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

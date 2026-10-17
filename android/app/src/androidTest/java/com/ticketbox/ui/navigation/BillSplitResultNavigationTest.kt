package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.isDialog
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.NavHostController
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.R
import com.ticketbox.data.remote.dto.BillSplitAcceptanceDto
import com.ticketbox.data.remote.dto.BillSplitInboxDto
import com.ticketbox.data.remote.dto.BillSplitInboxListResponseDto
import com.ticketbox.data.remote.dto.BillSplitReceivedBillDto
import com.ticketbox.data.remote.dto.BillSplitSentDto
import com.ticketbox.data.remote.dto.BillSplitSentListResponseDto
import com.ticketbox.data.remote.dto.LedgerDto
import com.ticketbox.data.remote.dto.LedgerListResponseDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.ui.saveConsumerArtPreview
import java.time.Instant
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Real Room, repository graph, both navigation controllers and ledger selection. */
class BillSplitResultNavigationTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val harness = FactEntryNavigationHarness(context)
    private val mounted = mutableStateOf(true)
    private val moshi = Moshi.Builder().addLast(KotlinJsonAdapterFactory()).build()
    private val targetName = "接收账本 · 家庭聚餐与旅行共同开销"
    private lateinit var outer: NavHostController

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun receiverUsesItsWritableTargetThenOpensTheActualResultWithoutMovingAnOldIntent() {
        val original = runBlocking { harness.saveFailedCorrection() }
        harness.fixture.role("viewer")
        configureLedgers("viewer", extraTarget = true)
        val row = requireNotNull(moshi.adapter(BillSplitInboxDto::class.java).fromJson(splitJson("invited")))
        harness.fixture.network.splitInbox = BillSplitInboxListResponseDto(listOf(row))
        val acceptedReply = requireNotNull(moshi.adapter(BillSplitAcceptanceDto::class.java).fromJson(splitJson("accepted"))).copy(
            receivedBill = BillSplitReceivedBillDto(84L, "received-ledger", targetName),
            acceptedTargetLedgerId = "received-ledger",
        )
        harness.fixture.network.splitAcceptReply = acceptedReply
        installSplitCenter()

        val review = context.getString(R.string.bill_split_review_invitation)
        waitForText(review)
        capture("split-inbox-list")
        compose.onNodeWithText(review).performScrollTo().performClick()
        val picker = context.getString(R.string.bill_split_accept_picker_title)
        waitForText(picker)
        compose.onNodeWithText(picker).performScrollTo().performClick()
        compose.onNodeWithText(targetName, useUnmergedTree = true).performClick()
        assertTrue(harness.fixture.network.splitAcceptCalls.isEmpty())
        compose.onNodeWithText(context.getString(R.string.bill_split_back_keep_selection)).performClick()
        compose.onNodeWithText(context.getString(R.string.bill_split_topbar_back)).performScrollTo().performClick()
        compose.waitForIdle()
        compose.runOnIdle { harness.shell.openSecondaryPage(ProductSecondaryPage.BillSplits) }
        waitForText(review)
        compose.onNodeWithText(review).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.bill_split_accept_selection, targetName)).performScrollTo().assertIsDisplayed()
        val accept = context.getString(R.string.bill_split_inbox_accept)
        waitForText(accept)
        capture("split-accept-selected")
        compose.onNodeWithText(accept).assertIsDisplayed()
        capture("split-accept-selected-actions")
        compose.onNodeWithText(accept).performClick()
        compose.waitUntil(5_000) { acceptanceRow() != null || harness.fixture.network.splitAcceptCalls.isNotEmpty() }
        assertTrue("Accept must persist its original target before sending; calls=${harness.fixture.network.splitAcceptCalls}",
            acceptanceRow() != null)
        assertTrue(harness.fixture.network.splitAcceptCalls.isEmpty())
        val originalAcceptance = requireNotNull(acceptanceRow())
        harness.fixture.network.loseSplitAcceptResponse = true
        assertEquals(1, runBlocking { harness.fixture.drainSplitAcceptance(maxAttempts = 1) }.failures)
        assertEquals("failed", acceptanceRow()?.get("status"))
        // Later reads may omit the original invitation while exposing its accepted bill.
        harness.fixture.network.splitInbox = BillSplitInboxListResponseDto(emptyList())
        harness.fixture.network.current = harness.fixture.network.current.copy(id = 84L, merchant = "已接受的分摊")
        val originalBinding = requireNotNull(harness.screenFactory.repository.captureDeferredLedgerBinding())
        harness.fixture.renewBinding()
        assertTrue(runBlocking { harness.screenFactory.repository.recoverBillSplitAcceptance(originalBinding,
            originalAcceptance.getValue("id")!!.toLong(), false) }.isFailure)
        compose.runOnIdle { mounted.value = false }
        compose.waitForIdle()
        harness.reopen()
        compose.runOnIdle { mounted.value = true }
        compose.runOnIdle { harness.shell.openSecondaryPage(ProductSecondaryPage.BillSplits) }
        val retry = context.getString(R.string.bill_split_accept_retry)
        waitForText(retry)
        compose.onNodeWithText(context.getString(R.string.bill_split_accept_original_target, targetName)).assertIsDisplayed()
        capture("split-accept-recovery")
        compose.onNodeWithText(retry).performScrollTo().assertIsDisplayed()
        capture("split-accept-recovery-actions")
        harness.fixture.network.loseSplitAcceptResponse = false
        harness.fixture.network.splitAcceptReply = acceptedReply.copy(acceptedTargetLedgerId = "wrong-target")
        retryAcceptance(retry)
        assertEquals(1, runBlocking { harness.fixture.drainSplitAcceptance() }.failures)
        assertEquals("bill_split_accept_response_unverified", acceptanceRow()?.get("lastError"))
        // Replay must retain the original target even if it no longer appears among writable choices.
        harness.fixture.network.splitLedgers = LedgerListResponseDto(requireNotNull(harness.fixture.network.splitLedgers).ledgers.map {
            if (it.ledgerId == "received-ledger") it.copy(role = "viewer") else it
        })
        harness.fixture.network.splitAcceptReply = acceptedReply
        compose.runOnIdle { harness.shell.openSecondaryPage(ProductSecondaryPage.ObligationSync) }
        waitForText(context.getString(R.string.sync_status_page_title))
        retryAcceptance(retry)
        assertEquals(1, runBlocking { harness.fixture.drainSplitAcceptance() }.done)
        compose.runOnIdle { harness.shell.openSecondaryPage(ProductSecondaryPage.BillSplits) }
        val completed = requireNotNull(acceptanceRow())
        for (field in listOf("payload", "idempotencyKey", "expectedRowVersion", "ownerKey", "ledgerId", "targetId")) {
            assertEquals("Original acceptance $field must remain unchanged", originalAcceptance[field], completed[field])
        }
        val received = context.getString(R.string.bill_split_open_received)
        waitForText(received)
        capture("split-accept-delivered")
        compose.onNodeWithText(received).performScrollTo().performClick()
        assertFactAndReturn(84L)

        assertEquals(List(3) { "result-split" to "received-ledger" }, harness.fixture.network.splitAcceptCalls)
        assertEquals(listOf("received-ledger"), harness.fixture.network.ledgerSwitchRequests)
        assertEquals("received-ledger", harness.screenFactory.ledgerRepository.activeLedgerId())
        assertEquals(original, harness.fixture.stored().single { it["id"] == original["id"] })
    }

    private fun acceptanceRow() = harness.fixture.stored().singleOrNull { it["type"] == "accept_bill_split_invitation" }

    private fun retryAcceptance(label: String) {
        waitForText(label)
        compose.onNodeWithText(label).performScrollTo().performClick()
        compose.waitUntil(5_000) { acceptanceRow()?.get("status") == "pending" }
    }

    @Test fun sentInvitationReturnsToItsOwnSourceRecord() {
        configureLedgers("member")
        val originalBinding = harness.screenFactory.repository.captureDeferredLedgerBinding()
        val row = requireNotNull(moshi.adapter(BillSplitSentDto::class.java).fromJson(splitJson("accepted")))
        harness.fixture.network.splitSent = BillSplitSentListResponseDto(listOf(row))
        installSplitCenter()

        val sent = context.getString(R.string.bill_split_tab_sent, 1)
        waitForText(sent)
        compose.onNodeWithText(sent).performScrollTo().performClick()
        val source = context.getString(R.string.bill_split_open_source)
        compose.onNodeWithText(source).performScrollTo().performClick()
        assertFactAndReturn(42L)

        assertTrue(harness.fixture.network.ledgerSwitchRequests.isEmpty())
        assertEquals(originalBinding, harness.screenFactory.repository.captureDeferredLedgerBinding())
        assertTrue(harness.fixture.stored().isEmpty())
        waitForText(source)
    }

    private fun configureLedgers(currentRole: String, extraTarget: Boolean = false) {
        harness.fixture.network.splitLedgers = LedgerListResponseDto(listOf(
            LedgerDto("correction-ledger", "家庭账本", currentRole, true, null, null),
            LedgerDto("received-ledger", targetName, "owner", false, null, null),
        ) + if (extraTarget) listOf(LedgerDto("wrong-ledger", "另一账本", "owner", false, null, null)) else emptyList())
    }

    private fun assertFactAndReturn(expenseId: Long) {
        waitForText(context.getString(R.string.expense_fact_original_spend))
        compose.onNodeWithTag("expense-fact").assertIsDisplayed()
        compose.runOnIdle {
            assertEquals(EXPENSE_ROUTE, outer.currentBackStackEntry?.destination?.route)
            assertEquals(expenseId, outer.currentBackStackEntry?.arguments?.getLong(EXPENSE_ID_ARG))
            assertTrue(harness.fixture.network.expenseReads.contains(expenseId))
            assertTrue(harness.fixture.network.calls.isEmpty())
        }
        compose.onNodeWithContentDescription(context.getString(R.string.expense_edit_primary_back_button))
            .performScrollTo().performClick()
        waitForText(context.getString(R.string.bill_split_topbar_title))
        assertEquals(MainProductDestination.Secondary(ProductSecondaryPage.BillSplits), harness.shell.activeDestination)
    }

    private fun waitForText(text: String) {
        compose.waitUntil(5_000) { compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty() }
    }

    private fun installSplitCenter() {
        compose.setContent {
            if (mounted.value) {
                CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                    TicketboxTheme(skin = if (InstrumentationRegistry.getArguments().getString("captureSkin") == "midnight")
                        AppSkin.Midnight else AppSkin.Paper) {
                        outer = rememberNavController()
                        MainNavGraph(MainNavigationRuntime(outer, harness.shell, harness.screenFactory),
                            remember { SnackbarHostState() },
                            SettingsPreferenceControls(AppSkin.Default, AppThemeMode.System, CurrencyCode.CNY,
                                onThemeModeChange = {}, onCurrencyChange = {}),
                            onBindingCleared = { error("Result navigation must preserve the session") })
                    }
                }
            }
        }
        compose.runOnIdle { harness.shell.openSecondaryPage(ProductSecondaryPage.BillSplits) }
    }

    private fun capture(name: String) {
        compose.waitForIdle()
        val target = if (compose.onAllNodes(isDialog()).fetchSemanticsNodes().isNotEmpty()) {
            compose.onNode(isDialog())
        } else compose.onRoot()
        saveConsumerArtPreview(name, target.captureToImage().asAndroidBitmap())
    }

    private fun splitJson(status: String): String = """{
      "public_id":"result-split","status":"$status","amount_cents":1200,"home_currency_code":"CNY",
      "merchant_snapshot":"Shared meal","category_suggestion":null,"expense_time_snapshot":null,
      "expires_at":"${Instant.now().plusSeconds(86_400)}","created_at":"2026-07-01T00:00:00Z",
      "accepted_at":null,"rejected_at":null,"cancelled_at":null,"expired_at":null,
      "sender_account_id":10,"sender_display_name":"Sender",
      "receiver_account_id":20,"receiver_display_name_snapshot":"Receiver","sender_expense_id":42
    }""".trimIndent()
}

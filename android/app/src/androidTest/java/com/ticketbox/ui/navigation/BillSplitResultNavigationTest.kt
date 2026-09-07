package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.NavHostController
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.R
import com.ticketbox.data.remote.dto.BillSplitInboxDto
import com.ticketbox.data.remote.dto.BillSplitInboxListResponseDto
import com.ticketbox.data.remote.dto.BillSplitSentDto
import com.ticketbox.data.remote.dto.BillSplitSentListResponseDto
import com.ticketbox.data.remote.dto.LedgerDto
import com.ticketbox.data.remote.dto.LedgerListResponseDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.theme.TicketboxTheme
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
    private lateinit var outer: NavHostController

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun receiverUsesItsWritableTargetThenOpensTheActualResultWithoutMovingAnOldIntent() {
        val original = runBlocking { harness.saveFailedCorrection() }
        harness.fixture.role("viewer")
        configureLedgers("viewer")
        val row = requireNotNull(moshi.adapter(BillSplitInboxDto::class.java).fromJson(splitJson("invited")))
        harness.fixture.network.splitInbox = BillSplitInboxListResponseDto(listOf(row))
        installSplitCenter()

        val accept = context.getString(R.string.bill_split_inbox_accept, "接收账本")
        waitForText(accept)
        compose.onNodeWithText(accept).performScrollTo().performClick()
        val received = context.getString(R.string.bill_split_open_received)
        waitForText(received)
        compose.onNodeWithText(context.getString(R.string.bill_split_received_ledger, "接收账本")).assertIsDisplayed()
        compose.onNodeWithText(received).performScrollTo().performClick()
        assertFactAndReturn(84L)

        assertEquals(listOf("result-split" to "received-ledger"), harness.fixture.network.splitAcceptCalls)
        assertEquals(listOf("received-ledger"), harness.fixture.network.ledgerSwitchRequests)
        assertEquals("received-ledger", harness.screenFactory.ledgerRepository.activeLedgerId())
        assertEquals(original, harness.fixture.stored().single())
        waitForText(received)
        compose.onNodeWithText(received).performScrollTo().assertIsDisplayed()
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

    private fun configureLedgers(currentRole: String) {
        harness.fixture.network.splitLedgers = LedgerListResponseDto(listOf(
            LedgerDto("correction-ledger", "家庭账本", currentRole, true, null, null),
            LedgerDto("received-ledger", "接收账本", "owner", false, null, null),
        ))
    }

    private fun assertFactAndReturn(expenseId: Long) {
        waitForText(context.getString(R.string.expense_fact_title))
        compose.onNodeWithText(context.getString(R.string.expense_fact_title)).assertIsDisplayed()
        compose.runOnIdle {
            assertEquals(EXPENSE_ROUTE, outer.currentBackStackEntry?.destination?.route)
            assertEquals(expenseId, outer.currentBackStackEntry?.arguments?.getLong(EXPENSE_ID_ARG))
            assertTrue(harness.fixture.network.expenseReads.contains(expenseId))
            assertTrue(harness.fixture.network.calls.isEmpty())
        }
        compose.onNode(hasContentDescription("") and hasClickAction()).performScrollTo().performClick()
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
                    TicketboxTheme(skin = AppSkin.Default) {
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

    private fun splitJson(status: String): String = """{
      "public_id":"result-split","status":"$status","amount_cents":1200,"home_currency_code":"CNY",
      "merchant_snapshot":"Shared meal","category_suggestion":null,"expense_time_snapshot":null,
      "expires_at":"${Instant.now().plusSeconds(86_400)}","created_at":"2026-07-01T00:00:00Z",
      "accepted_at":null,"rejected_at":null,"cancelled_at":null,"expired_at":null,
      "sender_account_id":10,"sender_display_name":"Sender",
      "receiver_account_id":20,"receiver_display_name_snapshot":"Receiver","sender_expense_id":42
    }""".trimIndent()
}

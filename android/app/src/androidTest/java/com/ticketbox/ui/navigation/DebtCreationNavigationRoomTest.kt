package com.ticketbox.ui.navigation

import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.compose.rememberNavController
import androidx.test.espresso.Espresso.closeSoftKeyboard
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtCreateRequestDto
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.DebtListResponseDto
import com.ticketbox.data.remote.dto.ExpenseAccountingTimeDto
import com.ticketbox.data.remote.dto.LedgerCalendarDto
import com.ticketbox.data.repository.CreateDebtDispatcher
import com.ticketbox.data.repository.DebtAdjustmentConnectedNetwork
import com.ticketbox.data.repository.OutboxDrainEngine
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.assertEditableTextEquals
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.screens.expense.LocalLedgerCalendarRepository
import com.ticketbox.ui.theme.TicketboxTheme
import java.io.IOException
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Actual MainNavGraph and disk Room. Only the remote API/session use controlled test data. */
class DebtCreationNavigationRoomTest {
    @get:Rule val compose = createComposeRule()
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val skin = if (InstrumentationRegistry.getArguments().getString("captureSkin") == "midnight") AppSkin.Midnight else AppSkin.Paper
    private val calls = CopyOnWriteArrayList<Pair<DebtCreateRequestDto, String?>>()
    private var acceptedRead = false
    private val response = DebtAdjustmentConnectedNetwork().current.copy(
        publicId = "created-original-debt", ledgerId = "correction-ledger", counterpartyLabel = "原往来 小王",
        direction = "i_owe", principalAmountCents = 12_345_678_901L, remainingAmountCents = 12_345_678_901L,
        paidAmountCents = 0, debtKind = "unspecified", note = null, installmentCount = null, installmentPeriodMonths = null,
        accountingTime = ExpenseAccountingTimeDto("date_only", userLocalDate = "2026-01-31", calendarRevision = 3))
    private var loseReply = true
    private lateinit var api: ApiService
    private val harness = FactEntryNavigationHarness(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun runtimeCompatibility() = delegate.runtimeCompatibility().let {
                it.copy(capabilities = it.capabilities.copy(accountingTimeInputVersion = 1))
            }
            override suspend fun debts(lens: String?) = DebtListResponseDto(if (acceptedRead) listOf(response) else emptyList(), "CNY")
            override suspend fun debtReceivables() = DebtListResponseDto(emptyList(), "CNY")
            override suspend fun debt(publicId: String) = response
            override suspend fun ledgerCalendar(ledgerId: String, revision: Long?) =
                LedgerCalendarDto(ledgerId, 3L, "Asia/Shanghai", "adopted", "2026-01-01T00:00:00Z")
            override suspend fun createDebt(request: DebtCreateRequestDto, idempotencyKey: String?): DebtDto {
                calls += request to idempotencyKey
                if (loseReply) throw IOException("Synthetic lost first receipt")
                return response
            }
        }.also { api = it }
    }

    @After fun close() { compose.runOnIdle { harness.models.viewModelStore.clear() }; harness.close() }

    @Test fun bothRealEntrypointsContinueOneOriginalThenShowTheAcceptedDebt() {
        mount()
        compose.onNodeWithText(text(R.string.nav_domain_obligations)).performClick()
        waitFor(text(R.string.debt_list_add))
        compose.onNodeWithText(text(R.string.debt_list_add)).performClick()
        field(R.string.debt_create_label_counterparty).performTextReplacement("原往来 小王")
        field(R.string.debt_create_label_amount).performScrollTo().performTextReplacement("123456789.01")
        field(R.string.debt_principal_date_label).performScrollTo().performTextReplacement("2026-01-31")
        closeSoftKeyboard()
        compose.onNodeWithText(text(R.string.debt_creation_keep_exit)).performClick()
        compose.onNodeWithText(text(R.string.relations_all_debts)).performScrollTo()
        compose.onNodeWithText(text(R.string.debt_list_add)).assertIsDisplayed()
        compose.onNodeWithText(text(R.string.relations_all_debts)).performClick()
        waitFor(text(R.string.debt_list_add))
        compose.onNodeWithText(text(R.string.debt_list_add)).performClick()
        field(R.string.debt_create_label_counterparty).assertEditableTextEquals("原往来 小王")
        field(R.string.debt_create_label_amount).assertEditableTextEquals("123456789.01")
        field(R.string.debt_principal_date_label).performScrollTo().assertEditableTextEquals("2026-01-31")
        compose.runOnIdle { harness.fixture.role("viewer") }
        waitFor(text(R.string.debt_creation_readonly_original))
        compose.onNodeWithText(text(R.string.debt_create_save)).assertIsNotEnabled()
        compose.onNodeWithText(text(R.string.debt_create_label_counterparty))
            .assertEditableTextEquals("原往来 小王").assertIsNotEnabled()
        capture("debt-original-readonly")
        compose.runOnIdle { harness.fixture.restoreOriginalSession() }
        compose.waitForIdle()
        compose.onNodeWithText(text(R.string.debt_create_label_direction)).performScrollTo()
        capture("debt-original-restored")
        compose.onNodeWithText(text(R.string.debt_create_save)).assertIsEnabled().performClick()
        waitFor(text(R.string.debt_create_local_saved))
        val original = harness.fixture.stored().single()
        assertTrue(calls.isEmpty())
        acceptedRead = true
        runBlocking { assertEquals(1, drain().retryable) }
        loseReply = false
        runBlocking {
            assertEquals(1, drain(harness.fixture.clock.millis() + 120_000).done)
        }
        assertEquals(2, calls.size)
        assertEquals(calls.first(), calls.last())
        assertEquals(original["idempotencyKey"], calls.last().second)
        assertEquals("原往来 小王", calls.last().first.counterpartyLabel)
        assertEquals("i_owe", calls.last().first.direction)
        assertEquals("unspecified", calls.last().first.debtKind)
        assertEquals(12_345_678_901L, calls.last().first.principalAmountCents)
        assertEquals("2026-01-31", calls.last().first.timeInput?.userLocalDate)
        waitFor(context.getString(R.string.debt_list_total_payable, "CNY"))
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("我欠原往来 小王"))
        compose.onNodeWithText("我欠原往来 小王").performClick()
        waitFor(text(R.string.debt_detail_principal))
        compose.onNodeWithText(text(R.string.debt_detail_principal)).assertIsDisplayed()
        compose.onNodeWithText(text(R.string.debt_detail_back)).performClick()
        waitFor("我欠原往来 小王")
        compose.onNodeWithText(text(R.string.debt_list_topbar_back)).performClick()
        waitFor("我欠原往来 小王")
        compose.onNodeWithText(text(R.string.debt_list_add)).assertIsDisplayed()
        capture("relations-root-populated")
        assertEquals(1, harness.fixture.stored().size)
    }

    private fun mount() {
        compose.setContent {
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models,
                LocalLedgerCalendarRepository provides harness.fixture.ledgerCalendarRepository) {
                TicketboxTheme(skin = skin) {
                    MainNavGraph(MainNavigationRuntime(rememberNavController(), harness.shell, harness.screenFactory),
                        remember { SnackbarHostState() },
                        SettingsPreferenceControls(AppSkin.Paper, AppThemeMode.System, CurrencyCode.CNY,
                            onThemeModeChange = {}, onCurrencyChange = {}), onBindingCleared = { error("Binding must remain") })
                }
            }
        }
    }
    private fun text(resource: Int) = context.getString(resource)
    private fun capture(name: String) {
        compose.waitForIdle()
        saveConsumerArtPreview(name, requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
    }
    private fun field(resource: Int) = compose.onNode(hasSetTextAction() and hasText(text(resource)))
    private fun waitFor(value: String) = compose.waitUntil(5_000) { compose.onAllNodesWithText(value).fetchSemanticsNodes().isNotEmpty() }
    private suspend fun drain(now: Long = harness.fixture.clock.millis()) = OutboxDrainEngine(harness.fixture.outbox,
        listOf(CreateDebtDispatcher({ api }, OutboxAdapterGraph().debtCreateAdapter)), now = { now }).drainOnce()
}

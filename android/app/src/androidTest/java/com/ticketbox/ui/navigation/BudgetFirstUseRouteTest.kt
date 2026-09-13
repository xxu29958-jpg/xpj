package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performTextReplacement
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.closeSoftKeyboard
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import com.ticketbox.data.repository.OutboxDrainEngine
import com.ticketbox.data.repository.SaveMonthlyBudgetDispatcher
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Real route and Room admission; only the budget HTTP transport is controlled. */
class BudgetFirstUseRouteTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val mounted = mutableStateOf(true)
    private val transport = FirstBudgetTransport()
    private val harness = FactEntryNavigationHarness(context, transport::wrap)
    private val adapters = OutboxAdapterGraph()

    @After fun close() {
        compose.runOnIdle { mounted.value = false }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun totalAlonePublishesOriginalYenBudgetAndShowsAdvancedFieldsAfterAcceptance() {
        show()
        compose.onNodeWithText(text(R.string.budget_editor_category_section_title)).assertDoesNotExist()
        input("budget_total_amount", "1200")
        save()
        compose.waitUntil(5_000) { runBlocking { harness.fixture.pendingDao.allRows().size == 1 } }
        val original = runBlocking { harness.fixture.pendingDao.allRows().single() }
        val intent = requireNotNull(adapters.budgetSaveAdapter.fromJson(original.payload))
        assertEquals(PendingMutationType.SaveMonthlyBudget.wireValue, original.type)
        assertEquals(0L, original.expectedRowVersion)
        assertEquals("correction-ledger", original.ledgerId)
        assertEquals(transport.reads.first(), intent.month)
        assertEquals(BudgetMonthlyUpdateRequestDto("JPY", null, 1200), intent.request)
        assertTrue(transport.writes.isEmpty())
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(text(R.string.budget_message_queued)))
            .fetchSemanticsNodes().isNotEmpty() }

        val engine = OutboxDrainEngine(harness.fixture.outbox, listOf(SaveMonthlyBudgetDispatcher(
            { transport.service }, adapters.budgetSaveAdapter, adapters.budgetReceiptAdapter)))
        assertEquals(1, runBlocking { engine.drainOnce().done })
        assertEquals(original.idempotencyKey, transport.writes.single().second)
        assertEquals(intent.request, transport.writes.single().first)
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasTestTag("budget_total_amount"))
        compose.waitUntil(5_000) { compose.onAllNodes(hasTestTag("budget_optional_fields"))
            .fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithTag("budget_optional_fields").performScrollTo().assertIsDisplayed()
        assertEquals(PendingMutationStatus.Done.wireValue, runBlocking { harness.fixture.pendingDao.allRows().single().status })
    }

    @Test fun advancedDraftAndItsErrorStayReachableWhileExpansionDoesNotLeakAcrossTasks() {
        show()
        openOptional()
        shiftMonth(R.string.budget_month_next)
        compose.onNodeWithText(text(R.string.budget_editor_category_section_title)).assertDoesNotExist()
        openOptional()
        input("budget_total_amount", "1200")
        input("budget_category_name", "餐饮")
        save()
        compose.onNodeWithText(text(R.string.budget_validation_category_amount_required)).performScrollTo().assertIsDisplayed()
        field("budget_category_name").performScrollTo().assertTextEquals("餐饮")
        assertTrue(runBlocking { harness.fixture.pendingDao.allRows().isEmpty() })

        shiftMonth(R.string.budget_month_next)
        compose.onNodeWithText(text(R.string.budget_editor_category_section_title)).assertDoesNotExist()
        shiftMonth(R.string.budget_month_previous)
        field("budget_category_name").performScrollTo().assertTextEquals("餐饮")
        transport.ledgerId = "another-ledger"
        compose.runOnIdle { harness.fixture.switchLedger() }
        compose.waitUntil(5_000) { transport.readLedgers.lastOrNull() == "another-ledger" }
        compose.onNodeWithText(text(R.string.budget_editor_total_label)).performScrollTo()
        compose.onNodeWithText(text(R.string.budget_editor_category_section_title)).assertDoesNotExist()
        assertTrue(runBlocking { harness.fixture.pendingDao.allRows().isEmpty() })
        assertTrue(transport.writes.isEmpty())
    }

    private fun show() {
        compose.setContent {
            if (mounted.value) TicketboxTheme(skin = AppSkin.Default) {
                NavHost(rememberNavController(), startDestination = "budget") {
                    composable("budget") { BudgetRoute(harness.screenFactory, onBack = {}) }
                }
            }
        }
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(text(R.string.budget_editor_total_label)))
            .fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText(text(R.string.budget_editor_total_label)).performScrollTo()
    }

    private fun field(tag: String) = compose.onNode(
        hasSetTextAction() and hasAnyAncestor(hasTestTag(tag)), useUnmergedTree = true)

    private fun input(tag: String, value: String) {
        field(tag).performScrollTo().performTextReplacement(value)
        field(tag).assertTextEquals(value)
        closeSoftKeyboard()
        compose.waitForIdle()
    }

    private fun save() { compose.onNodeWithText(text(R.string.budget_editor_save))
        .performScrollTo().assertIsEnabled().performClick() }

    private fun openOptional() { compose.onNodeWithTag("budget_optional_toggle").performScrollTo().performClick() }

    private fun shiftMonth(label: Int) {
        val count = transport.reads.size
        compose.onNodeWithText(text(label)).performScrollTo().performClick()
        compose.waitUntil(5_000) { transport.reads.size > count }
        compose.onNodeWithText(text(R.string.budget_editor_total_label)).performScrollTo()
    }

    private fun text(id: Int) = context.getString(id)
}

private class FirstBudgetTransport {
    val reads = CopyOnWriteArrayList<String>()
    val readLedgers = CopyOnWriteArrayList<String>()
    val writes = CopyOnWriteArrayList<Pair<BudgetMonthlyUpdateRequestDto, String?>>()
    @Volatile var ledgerId = "correction-ledger"
    private var accepted: BudgetMonthlyDto? = null
    lateinit var service: ApiService

    fun wrap(delegate: ApiService): ApiService = object : ApiService by delegate {
        override suspend fun monthlyBudget(month: String, timezone: String?): BudgetMonthlyDto {
            val result = accepted ?: firstBudget(ledgerId, month)
            reads += month
            readLedgers += ledgerId
            return result
        }

        override suspend fun updateMonthlyBudget(month: String, request: BudgetMonthlyUpdateRequestDto,
            timezone: String?, idempotencyKey: String?): BudgetMonthlyDto {
            writes += request to idempotencyKey
            return firstBudget(ledgerId, month).copy(configured = true, rowVersion = 1,
                totalAmountCents = request.totalAmountCents, flexBudgetCents = request.totalAmountCents,
                remainingAmountCents = request.totalAmountCents).also { accepted = it }
        }
    }.also { service = it }
}

private fun firstBudget(ledgerId: String, month: String) = BudgetMonthlyDto(
    ledgerId = ledgerId, month = month, configured = false, homeCurrencyCode = "JPY", rowVersion = null,
    totalAmountCents = 0, rolloverAmountCents = 0, fixedAmountCents = 0, nonMonthlyAmountCents = 0,
    flexBudgetCents = 0, spentAmountCents = 0, excludedAmountCents = 0, remainingAmountCents = 0,
    overspentAmountCents = 0, excludedCategories = emptyList(), excludedBreakdown = emptyList(),
    categoryBudgets = emptyList(), updatedAt = null,
)

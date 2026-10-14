package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertTextEquals
import com.ticketbox.ui.assertEditableTextEquals
import androidx.compose.ui.test.click
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isDialog
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performScrollToIndex
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.test.performTextReplacement
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.text.TextLayoutResult
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.closeSoftKeyboard
import androidx.test.platform.app.InstrumentationRegistry
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
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.RealKeyboard
import com.ticketbox.ui.theme.TicketboxTheme
import java.time.YearMonth
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
    @get:Rule val keyboard = RealKeyboard()
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

    @Test fun totalAlonePublishesOriginalYenBudgetAndReturnsToItsExecution() {
        show()
        compose.onNodeWithText(text(R.string.budget_editor_category_section_title)).assertExists()
        compose.onNodeWithTag("budget_optional_fields").assertDoesNotExist()
        input("budget_total_amount", "1200")
        field("budget_total_amount").performClick()
        keyboard.assertActionAboveKeyboard(compose, text(R.string.budget_editor_save), "budget-save-keyboard")
        save()
        keyboard.dismissAndWait(compose)
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
            { transport.service }, adapters.budgetSaveAdapter, adapters.budgetReceiptAdapter,
            harness.fixture.graph.budgetRepository.invalidateBudgetReadsAfterDelivery)),
            now = harness.fixture.clock::millis)
        assertEquals(1, runBlocking { engine.drainOnce().done })
        assertEquals(original.idempotencyKey, transport.writes.single().second)
        assertEquals(intent.request, transport.writes.single().first)
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(text(R.string.budget_editor_title))).fetchSemanticsNodes().isEmpty() }
        compose.onNode(hasScrollToIndexAction()).performScrollToIndex(0)
        compose.onNodeWithText(text(R.string.budget_header_title)).assertIsDisplayed()
        saveConsumerArtPreview("budget-execution-paper", requireNotNull(
            InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        compose.onNodeWithTag("budget_edit_open").assertIsDisplayed().performClick()
        compose.onNodeWithTag("budget_optional_fields").assertDoesNotExist()
        openOptional()
        compose.onNodeWithTag("budget_optional_fields").assertIsDisplayed()
        compose.onNodeWithText(text(R.string.budget_optional_return)).performClick()
        assertEquals(PendingMutationStatus.Done.wireValue, runBlocking { harness.fixture.pendingDao.allRows().single().status })
    }

    @Test fun advancedDraftAndItsErrorStayReachableWhileExpansionDoesNotLeakAcrossTasks() {
        show()
        openOptional()
        compose.onNodeWithText(text(R.string.budget_optional_return)).performClick()
        shiftMonth(R.string.budget_month_next)
        compose.onNodeWithTag("budget_optional_fields").assertDoesNotExist()
        openOptional()
        val rollover = compose.onNode(hasText(text(R.string.budget_editor_rollover_label)) and hasSetTextAction())
        rollover.performScrollTo().performTextReplacement("200")
        keyboard.assertActionAboveKeyboard(compose, text(R.string.budget_optional_return), "budget-optional-keyboard")
        compose.onNodeWithText(text(R.string.budget_optional_return)).performClick()
        keyboard.dismissAndWait(compose)
        input("budget_total_amount", "1200")
        input("budget_category_name", "餐饮")
        save()
        val error = text(R.string.budget_validation_category_amount_required)
        compose.onNodeWithText(error).assertIsDisplayed()
        field("budget_category_name").performScrollTo().assertTextEquals("餐饮")
        openOptional()
        rollover.performScrollTo().assertEditableTextEquals("200")
        saveConsumerArtPreview("budget-optional-draft", requireNotNull(
            InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        compose.onNodeWithText(text(R.string.budget_optional_return)).performClick()
        assertTrue(runBlocking { harness.fixture.pendingDao.allRows().isEmpty() })

        shiftMonth(R.string.budget_month_next)
        compose.onNodeWithTag("budget_optional_fields").assertDoesNotExist()
        shiftMonth(R.string.budget_month_previous)
        field("budget_category_name").performScrollTo().assertTextEquals("餐饮")
        transport.ledgerId = "another-ledger"
        compose.runOnIdle { harness.fixture.switchLedger() }
        compose.waitUntil(5_000) { transport.readLedgers.lastOrNull() == "another-ledger" }
        compose.onNodeWithText(text(R.string.budget_editor_total_label)).performScrollTo()
        compose.onNodeWithTag("budget_optional_fields").assertDoesNotExist()
        assertTrue(runBlocking { harness.fixture.pendingDao.allRows().isEmpty() })
        assertTrue(transport.writes.isEmpty())
    }

    @Test fun historyOpensFromTheRealBudgetAndKeepsTheOriginalYenAndCategoriesAcrossPages() {
        show()
        saveConsumerArtPreview("budget-editor-header", requireNotNull(
            InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        val headings = listOf(text(R.string.budget_editor_title),
            context.getString(R.string.budget_header_subtitle, monthLabel(transport.reads.first())))
        for (heading in headings) {
            val layouts = mutableListOf<TextLayoutResult>()
            compose.onNode(hasText(heading) and hasAnyAncestor(isDialog()), useUnmergedTree = true)
                .performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
            // String semantics rebuilds a MultiParagraph at the parent's max width, even
            // when the rendered Text wraps its width. Check the visible lines, not that box.
            assertTrue("The budget heading must remain readable: $heading; $layouts", layouts.isNotEmpty() && layouts.all { layout ->
                !layout.didOverflowHeight && (0 until layout.lineCount).all { line ->
                    !layout.isLineEllipsized(line) && layout.getLineLeft(line) >= 0f &&
                        layout.getLineRight(line) <= layout.size.width
                }
            })
        }
        compose.onNodeWithText(text(R.string.budget_editor_back)).assertIsDisplayed().performClick()
        compose.onNodeWithText(text(R.string.budget_history_title)).performScrollTo().performTouchInput { click() }
        val modified = context.getString(R.string.goal_history_version, 2, text(R.string.budget_history_edit))
        compose.waitUntil(5_000) { compose.onAllNodesWithText(modified).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText(modified).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(text(R.string.budget_history_more)).performScrollTo().performClick()
        val created = context.getString(R.string.goal_history_version, 1, text(R.string.budget_history_create))
        compose.waitUntil(5_000) { compose.onAllNodesWithText(created).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText(created).performScrollTo().assertIsDisplayed()
        compose.onAllNodesWithText(text(R.string.plan_history_expand))[1].performScrollTo().performClick()
        compose.onNodeWithText("餐饮 · JPY ¥300").performScrollTo().assertIsDisplayed()
        compose.waitForIdle()
        val bitmap = requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot())
        saveConsumerArtPreview("budget-history-jpy", bitmap)
        assertEquals(listOf(null, 2L), transport.historyCursors.toList())
        assertTrue(transport.writes.isEmpty())
        assertTrue(runBlocking { harness.fixture.pendingDao.allRows().isEmpty() })
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
        .assertIsDisplayed().assertIsEnabled().performClick() }

    private fun openOptional() { compose.onNodeWithTag("budget_optional_toggle").performScrollTo().performClick() }

    private fun shiftMonth(label: Int) {
        compose.onNodeWithText(text(R.string.budget_editor_back)).assertIsDisplayed().performClick()
        val count = transport.reads.size
        compose.onNodeWithText(text(label)).performScrollTo().performClick()
        compose.waitUntil(5_000) { transport.reads.size > count }
        compose.onNodeWithText(text(R.string.budget_editor_total_label)).performScrollTo()
    }

    private fun monthLabel(month: String) = YearMonth.parse(month).let {
        context.getString(R.string.components_month_label, it.year.toString(), it.monthValue.toString())
    }
    private fun text(id: Int) = context.getString(id)
}

private class FirstBudgetTransport {
    val historyCursors = CopyOnWriteArrayList<Long?>()
    val reads = CopyOnWriteArrayList<String>()
    val readLedgers = CopyOnWriteArrayList<String>()
    val writes = CopyOnWriteArrayList<Pair<BudgetMonthlyUpdateRequestDto, String?>>()
    @Volatile var ledgerId = "correction-ledger"
    private var accepted: BudgetMonthlyDto? = null
    lateinit var service: ApiService

    fun wrap(delegate: ApiService): ApiService = object : ApiService by delegate {
        override suspend fun budgetHistory(month: String, beforeVersion: Long?): com.ticketbox.data.remote.dto.BudgetHistoryDto {
            historyCursors += beforeVersion
            val initial = beforeVersion != null
            return com.ticketbox.data.remote.dto.BudgetHistoryDto(ledgerId, month,
                listOf(com.ticketbox.data.remote.dto.BudgetRevisionDto(if (initial) 1 else 2,
                    if (initial) "create" else "edit", "2026-09-26T00:00:00Z",
                    com.ticketbox.data.remote.dto.BudgetArrangementDto("JPY", if (initial) 1200 else 1500,
                        100, -20, listOf("旅行"), if (initial) listOf(
                            com.ticketbox.data.remote.dto.BudgetCategoryRequestDto("餐饮", 300)) else emptyList(), false))),
                if (initial) null else 2)
        }

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

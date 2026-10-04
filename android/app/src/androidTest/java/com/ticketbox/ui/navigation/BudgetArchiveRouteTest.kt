package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.closeSoftKeyboard
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.BudgetMonthlyArchiveRequestDto
import com.ticketbox.data.remote.dto.BudgetMonthlyArchiveResponseDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.R
import com.ticketbox.ui.theme.TicketboxTheme
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertTrue
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/** The actual budget route must expose a deliberate, cancelable archive action. */
class BudgetArchiveRouteTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val mounted = mutableStateOf(true)
    private val archives = java.util.concurrent.CopyOnWriteArrayList<Pair<String, Long>>()
    private var archived = false
    private val harness = FactEntryNavigationHarness(context, ::wrap)

    private fun wrap(delegate: ApiService): ApiService = object : ApiService by delegate {
        override suspend fun monthlyBudget(month: String, timezone: String?) = BudgetMonthlyDto(
            ledgerId = "correction-ledger", month = month, configured = !archived, homeCurrencyCode = "JPY", rowVersion = if (archived) null else 7,
            totalAmountCents = 1200, rolloverAmountCents = 0, fixedAmountCents = 0, nonMonthlyAmountCents = 0,
            flexBudgetCents = 1200, spentAmountCents = 0, excludedAmountCents = 0, remainingAmountCents = 1200,
            overspentAmountCents = 0, excludedCategories = emptyList(), excludedBreakdown = emptyList(),
            categoryBudgets = emptyList(), updatedAt = "2026-09-29T00:00:00Z",
        )

        override suspend fun archiveMonthlyBudget(month: String, request: BudgetMonthlyArchiveRequestDto): BudgetMonthlyArchiveResponseDto {
            archives += month to request.expectedRowVersion
            archived = true
            return BudgetMonthlyArchiveResponseDto("月度预算已移入回收站。")
        }
    }

    @After fun close() {
        compose.runOnIdle { mounted.value = false }
        compose.waitForIdle()
        harness.close()
    }

    private fun show() {
        compose.setContent {
            if (mounted.value) TicketboxTheme(skin = AppSkin.Default) {
                NavHost(rememberNavController(), startDestination = "budget") {
                    composable("budget") { BudgetRoute(harness.screenFactory, onBack = {}) }
                }
            }
        }
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(context.getString(R.string.budget_status_badge_active)))
            .fetchSemanticsNodes().isNotEmpty() }
    }

    private fun openArchive() {
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("将本月预算移入回收站"))
        compose.onNodeWithText("将本月预算移入回收站").performClick()
        compose.onNodeWithText("移入回收站？").assertIsDisplayed()
    }

    @Test fun configuredBudgetOffersArchiveAndCancelDoesNotCreateACommand() {
        show()
        openArchive()
        compose.onNodeWithText("取消").performClick()
        compose.onNodeWithText("移入回收站？").assertDoesNotExist()
        assertTrue(archives.isEmpty())
        assertTrue(runBlocking { harness.fixture.pendingDao.allRows().isEmpty() })
    }

    @Test fun confirmedArchiveUsesTheReadVersionAndRetainsAnUnsavedOriginalDraft() {
        show()
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasTestTag("budget_edit_open"))
        compose.onNodeWithTag("budget_edit_open").performClick()
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasTestTag("budget_total_amount"))
        val field = compose.onNode(hasSetTextAction() and hasAnyAncestor(hasTestTag("budget_total_amount")), useUnmergedTree = true)
        field.performScrollTo().performTextReplacement("1500")
        closeSoftKeyboard()
        compose.onNodeWithContentDescription(context.getString(R.string.budget_editor_back)).performScrollTo().performClick()
        openArchive()
        compose.onNodeWithText("移入回收站").performClick()
        compose.waitUntil(5_000) { archives.isNotEmpty() }
        assertEquals(7L, archives.single().second)
        compose.waitUntil(5_000) { compose.onAllNodes(hasText("预算已移入回收站，原支出和修改记录保留。"))
            .fetchSemanticsNodes().isNotEmpty() }
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasTestTag("budget_total_amount"))
        field.performScrollTo().assertTextEquals("1500")
        assertTrue(runBlocking { harness.fixture.pendingDao.allRows().isEmpty() })
    }
}

package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollToNode
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** The actual budget route must expose a deliberate, cancelable archive action. */
class BudgetArchiveRouteTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val mounted = mutableStateOf(true)
    private val harness = FactEntryNavigationHarness(context, ::wrap)

    private fun wrap(delegate: ApiService): ApiService = object : ApiService by delegate {
        override suspend fun monthlyBudget(month: String, timezone: String?) = BudgetMonthlyDto(
            ledgerId = "correction-ledger", month = month, configured = true, homeCurrencyCode = "JPY", rowVersion = 7,
            totalAmountCents = 1200, rolloverAmountCents = 0, fixedAmountCents = 0, nonMonthlyAmountCents = 0,
            flexBudgetCents = 1200, spentAmountCents = 0, excludedAmountCents = 0, remainingAmountCents = 1200,
            overspentAmountCents = 0, excludedCategories = emptyList(), excludedBreakdown = emptyList(),
            categoryBudgets = emptyList(), updatedAt = "2026-09-29T00:00:00Z",
        )
    }

    @After fun close() {
        compose.runOnIdle { mounted.value = false }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun configuredBudgetOffersArchiveAndCancelDoesNotCreateACommand() {
        compose.setContent {
            if (mounted.value) TicketboxTheme(skin = AppSkin.Default) {
                NavHost(rememberNavController(), startDestination = "budget") {
                    composable("budget") { BudgetRoute(harness.screenFactory, onBack = {}) }
                }
            }
        }
        compose.waitUntil(5_000) { compose.onAllNodes(hasText("预算设置")).fetchSemanticsNodes().isNotEmpty() }
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("将本月预算移入回收站"))
        compose.onNodeWithText("将本月预算移入回收站").performClick()
        compose.onNodeWithText("移入回收站？").assertIsDisplayed()
        compose.onNodeWithText("取消").performClick()
        compose.onNodeWithText("移入回收站？").assertDoesNotExist()
        assertTrue(runBlocking { harness.fixture.pendingDao.allRows().isEmpty() })
    }
}

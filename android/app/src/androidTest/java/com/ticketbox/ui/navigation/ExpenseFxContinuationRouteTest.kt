package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.closeSoftKeyboard
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BackgroundTaskDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseItemsResponseDto
import com.ticketbox.data.remote.dto.ExpenseSplitsResponseDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/** Real Route + VM + binding-aware repository; task observations cannot replace the local editor. */
class ExpenseFxContinuationRouteTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val mounted = mutableStateOf(true)
    private var currentTask = BackgroundTaskDto("fx-1", "expense_fx", "failed",
        createdAt = "2026-09-12T00:00:00Z", sourceExpenseId = 9)
    private var converted = false
    private var reads = 0
    private val retryVersions = mutableListOf<Long>()
    private var confirmed = 0
    private val harness = FactEntryNavigationHarness(context) { api -> object : ApiService by api {
        override suspend fun expense(id: Long): ExpenseDto {
            reads++
            return api.expense(id).copy(id = id, publicId = "expense-$id", status = "pending", category = "餐饮", originalCurrency = "USD", homeCurrency = "CNY",
                originalAmount = "10.00", originalAmountMinor = 1000, amountCents = if (converted) 7000 else null,
                homeAmountCents = if (converted) 7000 else null, fxRate = if (converted) "7" else null,
                fxRateDate = if (converted) "2026-09-11" else null, fxSource = if (converted) "reference" else null,
                fxStatus = if (converted) "ready" else "pending", fxTask = currentTask,
                rowVersion = if (converted) 2 else 1,
                updatedAt = if (converted) "2026-09-12T01:00:00Z" else "2026-09-12T00:00:00Z")
        }
        override suspend fun expenseFx(id: Long): BackgroundTaskDto = currentTask
        override suspend fun expenseItems(id: Long): ExpenseItemsResponseDto = api.expenseItems(id).copy(
            rowVersion = if (converted) 2 else 1,
            parentAmountCents = if (converted) 7000 else null,
        )
        override suspend fun expenseSplits(id: Long): ExpenseSplitsResponseDto = api.expenseSplits(id).copy(
            rowVersion = if (converted) 2 else 1,
            parentAmountCents = if (converted) 7000 else null,
        )
        override suspend fun getBackgroundTask(publicId: String): BackgroundTaskDto = error("initiator-only task endpoint")
        override suspend fun retryExpenseFx(id: Long, request: ExpenseStateTokenRequest): BackgroundTaskDto {
            retryVersions += request.expectedRowVersion
            currentTask = currentTask.copy(status = "queued")
            return currentTask
        }
        override suspend fun confirmExpense(id: String, request: ExpenseStateTokenRequest, idempotencyKey: String?): ExpenseDto {
            confirmed++
            error("FX cannot auto-confirm")
        }
    } }

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun retryThenCompletedObservationPreservesDraftUntilExplicitCleanReview() {
        compose.setContent {
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Default) {
                    if (mounted.value) ExpenseEditRoute(9, harness.screenFactory, ExpenseEditExitActions({}, {}), ExpenseFactNavigation({}, { _, _ -> }))
                }
            }
        }
        val retry = context.getString(R.string.expense_fx_retry)
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(retry)).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText(retry).performScrollTo().performClick()
        compose.waitUntil(5_000) { retryVersions.isNotEmpty() }
        assertEquals(listOf(1L), retryVersions)
        compose.onAllNodes(hasSetTextAction())[0].performTextReplacement("12.34")
        closeSoftKeyboard()
        compose.runOnIdle { currentTask = currentTask.copy(status = "completed"); converted = true }
        compose.onNodeWithText(context.getString(R.string.expense_fx_refresh)).performScrollTo().performClick()
        val load = context.getString(R.string.expense_fx_load_review)
        compose.waitUntil(5_000) { compose.onAllNodes(hasText(load)).fetchSemanticsNodes().isNotEmpty() }
        compose.onAllNodes(hasSetTextAction())[0].assertTextEquals("12.34")
        compose.onNodeWithText(load).assertIsNotEnabled()
        assertEquals(1, reads)
        assertEquals(0, confirmed)
        compose.onAllNodes(hasSetTextAction())[0].performTextReplacement("10.00")
        closeSoftKeyboard()
        compose.onNodeWithText(load).performScrollTo().performClick()
        compose.waitUntil(5_000) { reads == 2 }
        compose.waitForIdle()
        compose.onAllNodes(hasSetTextAction())[0].assertTextEquals("10.00")
        assertEquals(0, confirmed)
        compose.onNodeWithText("2026-09-11", substring = true).performScrollTo().assertExists()
    }
}

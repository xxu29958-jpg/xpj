package com.ticketbox.ui.screens.settings

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.OutboxStatus
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.OutboxStatusUiState
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class ManualExpenseSyncRetryConnectedTest {
    @JvmField
    @Rule
    val composeRule = createComposeRule()

    @Test
    fun unverifiableMoneyShowsReviewCopyAndNoRetry() {
        var retries = 0
        show("manual_create_original_unverified", "{\"client_ref\":\"original\",\"amount_cents\":1200}") { retries += 1 }
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        composeRule.onNodeWithText(context.getString(R.string.ledger_manual_original_unverified))
            .performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText(context.getString(R.string.sync_status_failed_button_retry)).assertDoesNotExist()
        composeRule.runOnIdle { assertEquals(0, retries) }
    }

    @Test
    fun temporaryFailureStillOffersTheOriginalRetry() {
        var retries = 0
        show("temporary failure") { retries += 1 }
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        composeRule.onNodeWithText(context.getString(R.string.sync_status_failed_button_retry))
            .performScrollTo().performClick()
        composeRule.runOnIdle { assertEquals(1, retries) }
    }

    private fun show(
        lastError: String,
        payloadJson: String = "{\"client_ref\":\"original\",\"original_currency\":\"CNY\",\"original_amount\":\"12.00\"}",
        retry: () -> Unit,
    ) {
        val row = OutboxRow(id = 11, serverUrl = "https://qa.invalid", ledgerId = "ledger",
            type = PendingMutationType.CreateExpense, targetId = "expense:local:original",
            payloadJson = payloadJson, expectedRowVersion = 0, status = PendingMutationStatus.Failed,
            retryCount = 0, lastError = lastError, createdAt = "2026-09-09T00:00:00Z",
            attemptedAt = null, completedAt = null)
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                SyncStatusScreenContent(
                    state = OutboxStatusUiState(bindingReady = true, status = OutboxStatus(0, emptyList(), listOf(row))),
                    actions = SyncStatusActions(onOpenRateSubmission = {}, onOpenIncomeSubmission = {},
                        onOpenRuleSubmission = {}, onOpenGoalEdit = {}, onOpenGoalCreation = {},
                        onOpenRecurring = {}, onOpenBudget = {}, onOpenExpense = {}, onKeepMine = {},
                        onDropMine = {}, onRetry = { retry() }, onDropFailed = {}, onClearQuarantined = {}),
                    onBack = {}, onOpenInbox = {},
                )
            }
        }
    }
}

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

    @Test
    fun missingReceiptOpensOnlyTheServerIdentifiedFactWithoutRetry() {
        var opened: Long? = null
        show("manual_create_original_requires_review:71", open = { opened = it }) { error("Unverifiable receipt cannot retry") }
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        composeRule.onNodeWithText(context.getString(R.string.error_manual_create_original_requires_review)).performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText(context.getString(R.string.sync_status_failed_button_retry)).assertDoesNotExist()
        composeRule.onNodeWithText(context.getString(R.string.ledger_manual_review_existing)).performScrollTo().performClick()
        composeRule.runOnIdle { assertEquals(71L, opened) }
    }

    @Test
    fun missingReceiptWithoutIdentityNeverOpensAnUnrelatedFact() {
        show("manual_create_original_requires_review", open = { error("No original identity") }) { error("No retry") }
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        composeRule.onNodeWithText(context.getString(R.string.error_manual_create_original_requires_review)).performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText(context.getString(R.string.ledger_manual_review_existing)).assertDoesNotExist()
        composeRule.onNodeWithText(context.getString(R.string.sync_status_failed_button_retry)).assertDoesNotExist()
    }

    private fun show(
        lastError: String,
        payloadJson: String = "{\"client_ref\":\"original\",\"original_currency\":\"CNY\",\"original_amount\":\"12.00\"}",
        open: (Long) -> Unit = {},
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
                    state = OutboxStatusUiState(bindingReady = true, status = OutboxStatus(0, emptyList(), listOf(row)),
                        manualCreations = mapOf(row.id to com.ticketbox.data.repository.ManualExpenseCreationProjection(row, null))),
                    actions = SyncStatusActions(onRepairCorrectionRate = { _, _ -> }, onOpenRateSubmission = {}, onOpenIncomeSubmission = {},
                        onOpenRuleSubmission = {}, onOpenGoalEdit = {}, onOpenGoalCreation = {},
                        onOpenRecurring = {}, onOpenBudget = {}, onOpenExpense = open, onKeepMine = {},
                        onDropMine = {}, onRetry = { retry() }, onDropFailed = {}, onClearQuarantined = {}),
                    onBack = {}, onOpenInbox = {},
                )
            }
        }
    }
}

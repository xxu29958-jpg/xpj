package com.ticketbox.ui.screens.settings

import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.ExpenseCorrectionObservation
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.OutboxStatus
import com.ticketbox.data.repository.RecurringPendingIntent
import com.ticketbox.data.repository.RecurringPendingKind
import com.ticketbox.data.repository.RecurringPendingState
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.OutboxStatusUiState
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class RecurringGlobalRecoveryTest {
    @get:Rule val compose = createComposeRule()
    private val context = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun originalYenAmountDoesNotUseTheCurrentCnyDefault() {
        show(original())
        compose.onNodeWithText("JPY ¥1,200").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("¥12.00", substring = true).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.sync_status_failed_button_retry)).assertExists()
    }

    @Test
    fun unsupportedOriginalShowsItsRawNumberAndOffersReviewWithoutRetry() {
        var opened = false
        show(original().copy(homeCurrencyCode = null, hasSupportedIntent = false, canRetry = false)) { opened = true }
        compose.onNodeWithText(context.getString(R.string.recurring_original_amount_unknown, 1200L)).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.sync_status_failed_button_retry)).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.recurring_original_open)).performScrollTo().performClick()
        compose.runOnIdle { assertTrue(opened) }
    }

    private fun show(original: RecurringPendingIntent, onOpenRecurring: () -> Unit = {}) {
        val binding = LogicalSessionBinding("https://example.test", "owner", "owner", "session", "binding")
        val row = OutboxRow(id = 43, serverUrl = binding.serverUrl, ledgerId = binding.ledgerId, ownerKey = binding.ownerKey,
            type = PendingMutationType.CreateRecurringItem, targetId = original.targetId, payloadJson = "{}",
            expectedRowVersion = 0, status = PendingMutationStatus.Failed, retryCount = 10, lastError = null,
            createdAt = "2026-09-09T00:00:00Z", attemptedAt = null, completedAt = null, idempotencyKey = original.idempotencyKey)
        val state = OutboxStatusUiState(binding = binding, bindingReady = true,
            correctionObservation = ExpenseCorrectionObservation(LedgerAccessContext(binding, true), emptyList()),
            status = OutboxStatus(0, emptyList(), listOf(row)), recurringItems = mapOf(row.id to original))
        compose.setContent { TicketboxTheme(skin = AppSkin.Default) {
            CompositionLocalProvider(LocalCurrencyDisplay provides CurrencyDisplay(CurrencyCode.CNY)) {
                SyncStatusScreenContent(state, SyncStatusActions(onOpenIncomeSubmission = {}, onOpenRuleSubmission = {}, onOpenGoalEdit = {}, onOpenGoalCreation = {},
                    onOpenExpense = {}, onKeepMine = { error("Unexpected write") }, onDropMine = { error("Unexpected drop") },
                    onRetry = { error("Unexpected retry") }, onDropFailed = { error("Unexpected drop") }, onClearQuarantined = {},
                    onOpenBudget = {}, onOpenRecurring = onOpenRecurring,
                ), {}, {})
            }
        } }
    }

    private fun original() = RecurringPendingIntent(RecurringPendingKind.CREATE,
        "recurring_item_create:original-key", "original-key", RecurringPendingState.FAILED,
        merchant = "交通月票", baselineAmountCents = 1200, homeCurrencyCode = "JPY", hasSupportedIntent = true, canRetry = true)
}

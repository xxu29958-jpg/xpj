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
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.repository.ExpenseCorrectionObservation
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.OutboxStatus
import com.ticketbox.data.repository.PendingCategoryRuleSubmission
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.OutboxStatusUiState
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class CategoryRuleGlobalRecoveryTest {
    @get:Rule val compose = createComposeRule()
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private var opened: Long? = null
    private var dropped: OutboxRow? = null

    @Test fun originalYenCreateOpensItsExactSubmissionAndStopRequiresConfirmation() {
        show(create = true)
        compose.onNodeWithText("JPY", substring = true).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("¥12.00", substring = true).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.category_rule_submission_details)).performScrollTo().performClick()
        compose.onNodeWithText("original-rule-key", substring = true).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.category_rule_submission_open)).performScrollTo().performClick()
        compose.runOnIdle { assertEquals(43L, opened) }
        compose.onNodeWithText(context.getString(R.string.sync_status_failed_button_drop)).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.category_rule_submission_stop_body)).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.common_cancel)).performClick()
        compose.runOnIdle { assertEquals(null, dropped) }
    }

    @Test fun currencylessLegacyUpdateStaysReadableWithoutGenericRetry() {
        show(create = false, currency = null)
        compose.onNodeWithText("1200", substring = true).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.sync_status_failed_button_retry)).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.category_rule_submission_open)).performScrollTo().performClick()
        compose.runOnIdle { assertEquals(43L, opened) }
    }

    private fun show(create: Boolean, currency: String? = "JPY") {
        val binding = LogicalSessionBinding("https://example.test", "owner", "owner", "session", "binding")
        val row = OutboxRow(43, binding.serverUrl, binding.ledgerId, binding.ownerKey,
            if (create) PendingMutationType.CreateCategoryRule else PendingMutationType.UpdateCategoryRule,
            if (create) "category_rule_create:original-rule-key" else "category_rule:17", "{}", if (create) 0 else 3,
            PendingMutationStatus.Failed, 1, "client_upgrade_required", "2026-09-09T00:00:00Z", null, null, "original-rule-key")
        val pending = PendingCategoryRuleSubmission(row,
            CategoryRuleRequest("交通月票", "transport", true, 0, amountMinCents = 1200, homeCurrencyCode = currency),
            null, supported = currency != null)
        val state = OutboxStatusUiState(binding = binding, bindingReady = true,
            correctionObservation = ExpenseCorrectionObservation(LedgerAccessContext(binding, true), emptyList()),
            status = OutboxStatus(0, emptyList(), listOf(row)), categoryRules = mapOf(row.id to pending))
        compose.setContent { TicketboxTheme(skin = AppSkin.Default) {
            CompositionLocalProvider(LocalCurrencyDisplay provides CurrencyDisplay(CurrencyCode.CNY)) {
                SyncStatusScreenContent(state, SyncStatusActions(onOpenIncomeSubmission = {}, onOpenRuleSubmission = { opened = it },
                    onOpenGoalEdit = {}, onOpenGoalCreation = {}, onOpenRecurring = {}, onOpenBudget = {},
                    onOpenExpense = {}, onKeepMine = { error("Unexpected token rebase") }, onDropMine = { dropped = it },
                    onRetry = { error("Unexpected retry") }, onDropFailed = { dropped = it }, onClearQuarantined = {}), {}, {})
            }
        } }
    }
}

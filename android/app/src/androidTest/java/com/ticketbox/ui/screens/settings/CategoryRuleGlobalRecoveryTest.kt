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
import com.ticketbox.data.repository.PendingRuleApplication
import com.ticketbox.data.repository.RuleApplicationPayload
import com.ticketbox.data.remote.dto.RuleApplyConfirmedResponseDto
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
    private var refreshed: OutboxRow? = null

    @Test fun staleApplicationOpensItsOriginalAndStoppingRequiresExplicitConfirmation() {
        showApplication(accepted = false)
        compose.onNodeWithText(context.getString(R.string.rule_application_stale)).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.sync_status_failed_button_retry)).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.rule_application_open)).performScrollTo().performClick()
        compose.runOnIdle { assertEquals(44L, opened) }
        compose.onNodeWithText(context.getString(R.string.sync_status_failed_button_drop)).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.rule_application_stop_body)).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.common_cancel)).performClick()
        compose.runOnIdle { assertEquals(null, dropped) }
    }

    @Test fun acceptedApplicationWithReadonlyAccessOffersOnlyReadRefresh() {
        showApplication(accepted = true)
        compose.onNodeWithText(context.getString(R.string.rule_application_original)).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.rule_application_receipt, 1)).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.rule_application_refresh_action)).performScrollTo().performClick()
        compose.runOnIdle { assertEquals(44L, refreshed?.id) }
        compose.onNodeWithText(context.getString(R.string.sync_status_failed_button_retry)).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.rule_application_stop)).assertDoesNotExist()
    }

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
        showState(state)
    }

    private fun showApplication(accepted: Boolean) {
        val binding = LogicalSessionBinding("https://example.test", "owner", "owner", "session", "binding")
        val row = OutboxRow(44, binding.serverUrl, binding.ledgerId, binding.ownerKey,
            PendingMutationType.ApplyConfirmedRules, "rule_application:confirmed", "{}", 0,
            if (accepted) PendingMutationStatus.Done else PendingMutationStatus.Failed, 1,
            if (accepted) "rule_application_read_refresh_required" else "preview_stale", "2026-10-08T00:00:00Z",
            null, null, "original-application-key", receiptJson = if (accepted) "{}" else null)
        val pending = PendingRuleApplication(row, RuleApplicationPayload(previewToken = "original-preview", maxScan = 500,
            scanned = 9, expectedChanges = 1), if (accepted) RuleApplyConfirmedResponseDto(false, 9, 1,
            commandKey = row.idempotencyKey, applicationPublicId = "original-batch", scanLimit = 500) else null)
        showState(OutboxStatusUiState(binding = binding, bindingReady = true,
            correctionObservation = ExpenseCorrectionObservation(LedgerAccessContext(binding, !accepted), emptyList()),
            status = OutboxStatus(0, emptyList(), if (accepted) emptyList() else listOf(row),
                refreshRequired = if (accepted) listOf(row) else emptyList()), ruleApplications = mapOf(row.id to pending)))
    }

    private fun showState(state: OutboxStatusUiState) {
        compose.setContent { TicketboxTheme(skin = AppSkin.Default) {
            CompositionLocalProvider(LocalCurrencyDisplay provides CurrencyDisplay(CurrencyCode.CNY)) {
                SyncStatusScreenContent(state, SyncStatusActions(onRefreshAcceptedResult = { refreshed = it }, onRepairCorrectionRate = { _, _ -> }, onOpenRateSubmission = {}, onOpenIncomeSubmission = {}, onOpenRuleSubmission = { opened = it },
                    onOpenGoalEdit = {}, onOpenGoalCreation = {}, onOpenRecurring = {}, onOpenBudget = {},
                    onOpenExpense = {}, onKeepMine = { error("Unexpected token rebase") }, onDropMine = { dropped = it },
                    onRetry = { error("Unexpected retry") }, onDropFailed = { dropped = it }, onClearQuarantined = {}), {}, {})
            }
        } }
    }
}

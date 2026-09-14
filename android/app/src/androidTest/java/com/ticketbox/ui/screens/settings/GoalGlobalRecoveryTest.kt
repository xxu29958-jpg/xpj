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
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import com.ticketbox.data.repository.ExpenseCorrectionObservation
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.OutboxStatus
import com.ticketbox.data.repository.PendingGoalCreation
import com.ticketbox.data.repository.PendingGoalEdit
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.OutboxStatusUiState
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class GoalGlobalRecoveryTest {
    @get:Rule val compose = createComposeRule()
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private var opened: String? = null
    private var dropped: OutboxRow? = null

    @Test fun creationShowsOriginalYenAndOpensItsExactLocalSubmission() {
        show(create = true)
        compose.onNodeWithText("JPY", substring = true).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("¥12.00", substring = true).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.goal_creation_open)).performScrollTo().performClick()
        compose.runOnIdle { assertEquals("creation:43", opened) }
        compose.onNodeWithText(context.getString(R.string.sync_status_failed_button_drop)).performScrollTo().performClick()
        compose.onNodeWithText(context.getString(R.string.goal_submission_stop_body)).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.common_cancel)).performClick()
        compose.runOnIdle { assertEquals(null, dropped) }
    }

    @Test fun currencylessEditShowsRawAmountAndOpensOriginalGoalWithoutRetry() {
        show(create = false, currency = null)
        compose.onNodeWithText(context.getString(R.string.spending_goal_original_amount_unknown, 1200L), substring = true)
            .performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.sync_status_failed_button_retry)).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.goal_submission_open)).performScrollTo().performClick()
        compose.runOnIdle { assertEquals("goal:original-goal", opened) }
    }

    private fun show(create: Boolean, currency: String? = "JPY") {
        val binding = LogicalSessionBinding("https://example.test", "owner", "owner", "session", "binding")
        val row = OutboxRow(43, binding.serverUrl, binding.ledgerId, binding.ownerKey,
            if (create) PendingMutationType.CreateGoal else PendingMutationType.UpdateGoal,
            if (create) "goal_create:original-key" else "goal:original-goal", "{}", if (create) 0 else 2,
            PendingMutationStatus.Failed, 1, "client_upgrade_required", "2026-09-09T00:00:00Z", null, null, "original-key")
        val state = OutboxStatusUiState(binding = binding, bindingReady = true,
            correctionObservation = ExpenseCorrectionObservation(LedgerAccessContext(binding, true), emptyList()),
            status = OutboxStatus(0, emptyList(), listOf(row)),
            goalCreations = if (create) mapOf(row.id to PendingGoalCreation(row,
                GoalCreateRequestDto("交通", month = "2026-09", targetAmountCents = 1200, homeCurrencyCode = currency), null)) else emptyMap(),
            goalEdits = if (create) emptyMap() else mapOf(row.id to PendingGoalEdit(row,
                GoalUpdateRequestDto(2, "交通", "2026-09", targetAmountCents = 1200, homeCurrencyCode = currency), null)))
        compose.setContent { TicketboxTheme(skin = AppSkin.Default) {
            CompositionLocalProvider(LocalCurrencyDisplay provides CurrencyDisplay(CurrencyCode.CNY)) {
                SyncStatusScreenContent(state, SyncStatusActions(onRefreshExpense = {}, onRepairCorrectionRate = { _, _ -> }, onOpenRateSubmission = {}, onOpenIncomeSubmission = {}, onOpenRuleSubmission = {}, onOpenGoalEdit = { opened = "goal:$it" },
                    onOpenGoalCreation = { opened = "creation:$it" }, onOpenRecurring = {}, onOpenBudget = {},
                    onOpenExpense = {}, onKeepMine = { error("Unexpected write") }, onDropMine = { dropped = it },
                    onRetry = { error("Unexpected retry") }, onDropFailed = { dropped = it }, onClearQuarantined = {}), {}, {})
            }
        } }
    }
}

package com.ticketbox.ui.screens.settings

import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.MonthlyArrangementSaveRequest
import com.ticketbox.data.repository.*
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.OutboxStatusUiState
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class MonthlyArrangementGlobalRecoveryTest {
    @get:Rule val compose = createComposeRule()
    private val context = InstrumentationRegistry.getInstrumentation().targetContext

    @Test fun failedArrangementDisplaysOriginalMinorUnitsAndOpensItsMonth() {
        var opened: String? = null
        show(pending(), onOpen = { opened = it })
        compose.onNodeWithText(context.getString(R.string.arrangement_original_currency, "JPY"))
            .performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("¥3,000", substring = true).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("¥30.00", substring = true).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.arrangement_open_month)).performScrollTo().performClick()
        compose.runOnIdle { assertEquals("2026-07", opened) }
    }

    @Test fun unreadableArrangementStaysRecoverableWithoutGuessingAMonthOrOfferingRetry() {
        show(pending().copy(intent = null), onOpen = { error("Cannot guess original month") })
        compose.onNodeWithText(context.getString(R.string.arrangement_original_unsupported)).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.arrangement_open_month)).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.sync_status_failed_button_retry)).assertDoesNotExist()
    }

    private fun show(pending: PendingMonthlyArrangement, onOpen: (String) -> Unit) {
        val binding = LogicalSessionBinding("https://example.test", "owner", "owner", "session", "binding")
        val state = OutboxStatusUiState(binding = binding, bindingReady = true,
            status = OutboxStatus(0, emptyList(), listOf(pending.row)), arrangements = mapOf(pending.row.id to pending))
        compose.setContent { TicketboxTheme(skin = AppSkin.Default) {
            CompositionLocalProvider(LocalCurrencyDisplay provides CurrencyDisplay(CurrencyCode.CNY)) {
                SyncStatusScreenContent(state, SyncStatusActions(onOpenExpense = {}, onRefreshAcceptedResult = {},
                    onKeepMine = { error("No automatic overwrite") }, onDropMine = { error("No automatic stop") },
                    onRetry = { error("No automatic retry") }, onDropFailed = { error("No automatic stop") },
                    onClearQuarantined = {}, onOpenBudget = {}, onOpenRecurring = {}, onOpenGoalCreation = {},
                    onOpenGoalEdit = {}, onOpenRuleSubmission = {}, onOpenIncomeSubmission = {},
                    onOpenRateSubmission = {}, onRepairCorrectionRate = { _, _ -> }, onOpenArrangement = onOpen), {}, {})
            }
        } }
    }

    private fun pending() = PendingMonthlyArrangement(
        OutboxRow(id = 42, serverUrl = "https://example.test", ledgerId = "owner", ownerKey = "owner",
            type = PendingMutationType.SaveMonthlyArrangement, targetId = "monthly_arrangement:2026-07", payloadJson = "{}",
            expectedRowVersion = 1, status = PendingMutationStatus.Failed, retryCount = 0, lastError = null,
            createdAt = "2026-07-08T00:00:00Z", attemptedAt = null, completedAt = null, idempotencyKey = "arrangement-original-key"),
        MonthlyArrangementPayload(1, "2026-07", MonthlyArrangementSaveRequest("JPY", 3000, 500)), null)
}

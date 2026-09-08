package com.ticketbox.ui.screens.settings

import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollTo
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import com.ticketbox.data.repository.BudgetSavePayload
import com.ticketbox.data.repository.ExpenseCorrectionObservation
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.OutboxStatus
import com.ticketbox.data.repository.PendingBudgetSave
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.OutboxStatusUiState
import org.junit.Rule
import org.junit.Test

class BudgetGlobalRecoveryTest {
    @get:Rule val compose = createComposeRule()
    private val context = InstrumentationRegistry.getInstrumentation().targetContext

    @Test
    fun globalSyncShowsTheOriginalYenAmountUnderACnyDisplayDefault() {
        show(pending())
        compose.onNodeWithText("2026-09 · JPY").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("¥1,200", substring = true).assertIsDisplayed()
        compose.onNodeWithText("¥12.00", substring = true).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.sync_status_failed_button_retry)).assertExists()
    }

    @Test
    fun unsupportedGlobalBudgetPreservesTheOriginalWithoutOfferingRetry() {
        show(pending().copy(intent = null))
        compose.onNodeWithText(context.getString(R.string.budget_save_unsupported)).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.sync_status_failed_button_retry)).assertDoesNotExist()
    }

    private fun show(pending: PendingBudgetSave) {
        val binding = LogicalSessionBinding("https://example.test", "owner", "owner", "session", "binding")
        val state = OutboxStatusUiState(binding = binding, bindingReady = true,
            correctionObservation = ExpenseCorrectionObservation(LedgerAccessContext(binding, true), emptyList()),
            status = OutboxStatus(0, emptyList(), listOf(pending.row)), budgetSaves = mapOf(pending.row.id to pending))
        compose.setContent { TicketboxTheme(skin = AppSkin.Default) {
            CompositionLocalProvider(LocalCurrencyDisplay provides CurrencyDisplay(CurrencyCode.CNY)) {
                SyncStatusScreenContent(state, SyncStatusActions({}, {}, {}, {}, {}, {}), {}, {})
            }
        } }
    }

    private fun pending() = PendingBudgetSave(
        OutboxRow(id = 42, serverUrl = "https://example.test", ledgerId = "owner", ownerKey = "owner",
            type = PendingMutationType.SaveMonthlyBudget, targetId = "monthly_budget:2026-09", payloadJson = "{}",
            expectedRowVersion = 0, status = PendingMutationStatus.Failed, retryCount = 0, lastError = null,
            createdAt = "2026-09-08T00:00:00Z", attemptedAt = null, completedAt = null, idempotencyKey = "budget-original-key"),
        BudgetSavePayload(1, "2026-09", "UTC", BudgetMonthlyUpdateRequestDto("JPY", null, 1200)),
        null,
    )
}

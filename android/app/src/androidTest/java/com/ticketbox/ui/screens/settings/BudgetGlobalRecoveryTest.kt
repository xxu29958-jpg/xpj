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
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import com.ticketbox.data.repository.BudgetSavePayload
import com.ticketbox.data.repository.ExpenseCorrectionObservation
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.OutboxStatus
import com.ticketbox.data.repository.PendingBudgetSave
import com.ticketbox.data.repository.toDomain
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.navigation.offlineBudget
import com.ticketbox.ui.screens.budget.BudgetPendingSaves
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.OutboxStatusUiState
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.assertEquals

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
        compose.onNodeWithText(context.getString(R.string.budget_save_open_month)).assertDoesNotExist()
    }

    @Test
    fun originalBudgetOffersAnEntranceToItsMonth() {
        var openedMonth: String? = null
        show(pending(), onOpenBudget = { openedMonth = it })
        compose.onNodeWithText(context.getString(R.string.budget_save_open_month)).performScrollTo().performClick()
        compose.runOnIdle { assertEquals("2026-09", openedMonth) }
    }

    @Test fun acceptedBudgetWithLocalReadFailureOffersReadRecoveryAtGlobalSync() {
        val accepted = acceptedReadPending()
        var recovered: OutboxRow? = null
        show(accepted, onRead = { recovered = it })
        compose.onNodeWithText("预算已保存，显示待更新。").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("2026-09 · JPY").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("¥1,200", substring = true).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.sync_status_failed_button_retry)).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.budget_save_drop)).assertDoesNotExist()
        compose.onNodeWithText("重新读取预算").performScrollTo().performClick()
        compose.runOnIdle { assertEquals(accepted.row, recovered) }
    }

    @Test fun acceptedBudgetReadRecoveryStaysAvailableToAReaderAtTheBudgetEntrance() {
        val accepted = acceptedReadPending()
        var recovered: PendingBudgetSave? = null
        compose.setContent { TicketboxTheme(skin = AppSkin.Default) {
            BudgetPendingSaves(listOf(accepted), canModify = false) { original, drop ->
                check(!drop) { "An accepted save cannot be discarded as a failed command" }
                recovered = original
            }
        } }
        compose.onNodeWithText("预算已保存，显示待更新。").assertIsDisplayed()
        compose.onNodeWithText("2026-09 · JPY").assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.sync_status_failed_button_retry)).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.budget_save_drop)).assertDoesNotExist()
        compose.onNodeWithText("重新读取预算").performClick()
        compose.runOnIdle { assertEquals(accepted, recovered) }
    }

    private fun acceptedReadPending(): PendingBudgetSave {
        val receipt = offlineBudget().copy(rowVersion = 8)
        return pending().let { it.copy(
            row = it.row.copy(status = PendingMutationStatus.Done, lastError = "budget_read_refresh_required",
                receiptJson = com.ticketbox.OutboxAdapterGraph().budgetReceiptAdapter.toJson(receipt)),
            receipt = receipt.toDomain(),
        ) }
    }

    private fun show(pending: PendingBudgetSave, onOpenBudget: (String) -> Unit = {}, onRead: (OutboxRow) -> Unit = {}) {
        val binding = LogicalSessionBinding("https://example.test", "owner", "owner", "session", "binding")
        val state = OutboxStatusUiState(binding = binding, bindingReady = true,
            correctionObservation = ExpenseCorrectionObservation(LedgerAccessContext(binding, true), emptyList()),
            status = OutboxStatus(0, emptyList(), listOf(pending.row).filter { it.status == PendingMutationStatus.Failed },
                refreshRequired = listOf(pending.row).filter { it.status == PendingMutationStatus.Done }),
            budgetSaves = mapOf(pending.row.id to pending))
        compose.setContent { TicketboxTheme(skin = AppSkin.Default) {
            CompositionLocalProvider(LocalCurrencyDisplay provides CurrencyDisplay(CurrencyCode.CNY)) {
                SyncStatusScreenContent(state, SyncStatusActions(onRefreshAcceptedResult = onRead, onRepairCorrectionRate = { _, _ -> }, onOpenRateSubmission = {}, onOpenIncomeSubmission = {}, onOpenRuleSubmission = {}, onOpenGoalEdit = {}, onOpenGoalCreation = {}, onOpenRecurring = {},
                    onOpenExpense = {}, onKeepMine = { error("Unexpected write") },
                    onDropMine = { error("Unexpected drop") }, onRetry = { error("Unexpected retry") },
                    onDropFailed = { error("Unexpected drop") }, onClearQuarantined = {},
                    onOpenBudget = onOpenBudget,
                ), {}, {})
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

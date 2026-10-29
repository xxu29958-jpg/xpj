package com.ticketbox.ui.screens

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTextReplacement
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.viewmodel.openEnvelopes
import com.ticketbox.viewmodel.start
import com.ticketbox.viewmodel.voidActivity
import com.ticketbox.viewmodel.voidCreditApplication
import com.ticketbox.viewmodel.voidPayment
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Rule
import org.junit.Test

/** Every funds editor on the real screen at phone width: synthetic accounts, real ViewModel, Room and Outbox, no network. */
class FundsEditorRenderTest {
    @get:Rule val compose = createComposeRule()
    private val screen = FundsEditorDriver(compose)

    @After
    fun close() = screen.close()

    @Test
    fun openingAnAccountRestatesTheChangeBesideConfirm() = with(screen) {
        show()
        compose.onNodeWithText(text(R.string.funds_add_account)).performClick()
        awaitEditor("create")
        capture("funds-editor-create")
        field(text(R.string.funds_account_name)).performTextInput("工资卡")
        field(text(R.string.funds_opening_balance, "CNY")).performScrollTo().performTextInput("1200.00")
        summary("将添加银行卡「工资卡」，CNY，期初余额 1200.00 CNY（2026-10-19），仅我自己可见。").assertIsDisplayed()
        compose.onNodeWithText(text(R.string.funds_confirm_save)).assertIsDisplayed()
        capture("funds-editor-create-summary")
    }

    @Test
    fun creditAccountTermsInMidnight() = with(screen) {
        show(AppSkin.Midnight)
        compose.runOnIdle { vm.start("create") }
        awaitEditor("create")
        compose.onNodeWithText(text(R.string.funds_kind_credit)).performClick()
        field(text(R.string.funds_account_name)).performTextInput("招行信用卡")
        field(text(R.string.funds_opening_debt, "CNY")).performScrollTo().performTextInput("3790.00")
        compose.onNodeWithText(text(R.string.funds_terms_title)).performScrollTo()
        compose.runOnIdle { assertEquals("credit", vm.state.value.task.input?.kind) }
        capture("funds-editor-create-credit-midnight")
    }

    @Test
    fun incompleteAccountIsRefusedWhereConfirmWasPressed() = with(screen) {
        show()
        compose.runOnIdle { vm.start("create") }
        awaitEditor("create")
        compose.onNodeWithText(text(R.string.funds_confirm_save)).performClick()
        compose.waitUntil(10_000) { vm.state.value.error != null && !vm.state.value.busy }
        compose.onNodeWithText("请填写账户名称和期初依据。").assertIsDisplayed()
        compose.onNodeWithText(text(R.string.funds_confirm_save)).assertIsDisplayed()
        compose.runOnIdle { assertFalse(vm.state.value.task.frozen) }
        capture("funds-editor-create-validation")
    }

    @Test
    fun accountEditKeepsCreditTerms() = with(screen) {
        show()
        openAccount("huabei")
        compose.runOnIdle { vm.start("edit") }
        awaitEditor("edit")
        compose.onNodeWithText(text(R.string.funds_terms_title)).performScrollTo()
        capture("funds-editor-edit-credit")
    }

    @Test
    fun incomeTransferAndLoanNameTheirAccounts() = with(screen) {
        show()
        openAccount("bank")
        compose.onNodeWithText(text(R.string.funds_record_income)).performClick()
        awaitEditor("income")
        field("${text(R.string.funds_income_received)}（CNY）").performTextInput("8650.00")
        summary("「招商银行」将增加 8650.00 CNY。实际收入不算消费，也不改变收入计划。").assertIsDisplayed()
        capture("funds-editor-income")
        abandon()

        openAccount("bank")
        compose.onNodeWithText(text(R.string.funds_record_transfer)).performClick()
        awaitEditor("transfer")
        field("${text(R.string.funds_transfer_sent)}（CNY）").performTextInput("500.00")
        compose.onNodeWithText(text(R.string.funds_choose_receiver)).performScrollTo().performClick()
        compose.onNodeWithText("现金 · CNY").performClick()
        field(text(R.string.funds_receiver_amount, "CNY")).performScrollTo().performTextInput("500.00")
        summary("从「招商银行」转出 500.00 CNY，「现金」到账 500.00 CNY。不算收入或消费。").assertIsDisplayed()
        capture("funds-editor-transfer")
        abandon()

        openAccount("bank")
        compose.runOnIdle { vm.start("loan") }
        awaitEditor("loan")
        capture("funds-editor-loan")
    }

    @Test
    fun reconciliationStatesWhatAnAdjustmentWouldDo() = with(screen) {
        show()
        openAccount("huabei")
        compose.runOnIdle { vm.start("reconciliation") }
        awaitEditor("reconciliation")
        field("${text(R.string.funds_observed_debt)}（CNY）").performTextInput("37.90")
        summary(text(R.string.funds_preview_reconcile_snapshot, "37.90 CNY")).assertIsDisplayed()
        capture("funds-editor-reconciliation")
    }

    @Test
    fun repaymentAtLargeTextKeepsAmountsWhole() = with(screen) {
        show(fontScale = 2f)
        openAccount("huabei")
        compose.onNodeWithText(text(R.string.funds_record_actual_repayment)).performClick()
        awaitEditor("repay")
        compose.onNodeWithText(text(R.string.funds_choose_payer)).performScrollTo().performClick()
        compose.onNodeWithText("招商银行 · CNY").performClick()
        field(text(R.string.funds_principal, "CNY")).performScrollTo().performTextInput("37.90")
        capture("funds-editor-repay-large-text")
        summary("从「招商银行」扣款").assertIsDisplayed()
        capture("funds-editor-repay-large-text-summary")
    }

    @Test
    fun repaymentConflictOffersReviewInsteadOfResubmitting() = with(screen) {
        show()
        openAccount("huabei")
        compose.onNodeWithText(text(R.string.funds_record_actual_repayment)).performClick()
        awaitEditor("repay")
        compose.onNodeWithText(text(R.string.funds_choose_payer)).performScrollTo().performClick()
        compose.onNodeWithText("招商银行 · CNY").performClick()
        field(text(R.string.funds_principal, "CNY")).performScrollTo().performTextInput("37.90")
        field(text(R.string.funds_note)).performScrollTo().performTextInput("10 月账单")
        compose.onNodeWithText(text(R.string.funds_confirm_save)).performClick()
        compose.waitUntil(10_000) { vm.state.value.task.original?.status == PendingMutationStatus.Pending }
        compose.onNodeWithText(text(R.string.funds_receipt_pending)).assertIsDisplayed()
        capture("funds-editor-repay-pending")

        fixture.network.reply = fundsServerAnswer(409, "state_conflict", "花呗已在其他设备更新，请核对最新欠款后继续。")
        runBlocking { fixture.deliver() }
        compose.waitUntil(10_000) { vm.state.value.task.original?.status == PendingMutationStatus.Conflict }
        compose.onNodeWithText(text(R.string.funds_review_continue)).assertIsDisplayed()
        compose.onNodeWithText(text(R.string.funds_retry_original)).assertDoesNotExist()
        capture("funds-editor-repay-conflict")
    }

    @Test
    fun refusedIncomeKeepsTheOriginalForReviewInMidnight() = with(screen) {
        show(AppSkin.Midnight)
        openAccount("bank")
        compose.onNodeWithText(text(R.string.funds_record_income)).performClick()
        awaitEditor("income")
        field("${text(R.string.funds_income_received)}（CNY）").performTextInput("8650.00")
        field(text(R.string.funds_source_note)).performScrollTo().performTextInput("10 月工资")
        compose.onNodeWithText(text(R.string.funds_confirm_save)).performClick()
        compose.waitUntil(10_000) { vm.state.value.task.original != null }

        fixture.network.reply = fundsServerAnswer(422, "amount_invalid", "金额小数位与账户币种不一致。")
        runBlocking { fixture.deliver() }
        compose.waitUntil(10_000) { vm.state.value.task.original?.status == PendingMutationStatus.Failed }
        compose.onNodeWithText(text(R.string.funds_review_continue)).assertIsDisplayed()
        capture("funds-editor-income-refused-midnight")
    }

    @Test
    fun installmentScheduleListsOpenDrawsAndPeriods() = with(screen) {
        show()
        openAccount("huabei")
        compose.runOnIdle { vm.start("installments") }
        awaitEditor("installments")
        field(text(R.string.funds_agreement_name)).performTextReplacement("超市 3 期")
        compose.onNodeWithText(text(R.string.funds_add_period)).performScrollTo().performClick()
        field(text(R.string.funds_period_due, 1)).performScrollTo().performTextInput("2026-11-09")
        field(text(R.string.funds_period_principal)).performScrollTo().performTextInput("12.63")
        capture("funds-editor-installments")
    }

    @Test
    fun envelopeAllocationFillsFromThePlan() = with(screen) {
        show()
        compose.runOnIdle { vm.openEnvelopes("2026-10") }
        compose.waitUntil(10_000) { vm.state.value.envelopes != null }
        compose.onNodeWithText(text(R.string.envelopes_edit)).performScrollTo().performClick()
        awaitEditor("envelopes")
        compose.onNodeWithText(text(R.string.envelopes_fill_plan)).performScrollTo().performClick()
        capture("funds-editor-envelopes")
    }

    @Test
    fun correctionsSayWhatTheyUndo() = with(screen) {
        show()
        openAccount("bank")
        compose.runOnIdle { vm.voidActivity(requireNotNull(vm.state.value.detail).movements.single()) }
        awaitEditor("void_activity")
        capture("funds-editor-void-activity")
        abandon()

        openAccount("huabei")
        compose.runOnIdle { vm.voidPayment("repayment-oct") }
        awaitEditor("void_repayment")
        compose.onNodeWithText("10 月账单还款", substring = true).assertIsDisplayed()
        capture("funds-editor-void-repayment")
        abandon()

        openAccount("huabei")
        compose.runOnIdle { vm.voidCreditApplication("applied-1") }
        awaitEditor("void_credit")
        capture("funds-editor-void-credit")
    }

    @Test
    fun creditFeeAndRetainedCreditForms() = with(screen) {
        show()
        openAccount("huabei")
        compose.runOnIdle { vm.start("apply_credit") }
        awaitEditor("apply_credit")
        capture("funds-editor-apply-credit")
        abandon()

        openAccount("huabei")
        compose.runOnIdle { vm.start("incur_fee") }
        awaitEditor("incur_fee")
        field(text(R.string.funds_incurred_amount, "CNY")).performTextInput("4.50")
        capture("funds-editor-incur-fee")
    }

    @Test
    fun expenseFundingNamesThePayingAccount() = with(screen) {
        show(expenseId = 42)
        compose.waitUntil(10_000) { vm.state.value.funding != null }
        compose.onNodeWithText(text(R.string.funds_review_funding)).performClick()
        awaitEditor("funding")
        compose.onNodeWithText("花呗 · CNY").assertIsDisplayed()
        capture("funds-editor-funding")
    }
}

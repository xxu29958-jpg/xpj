package com.ticketbox.ui.screens

import androidx.compose.ui.test.click
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTouchInput
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.RealKeyboard
import org.junit.After
import org.junit.Rule
import org.junit.Test

/** Real OS keyboard: while an amount is typed, the form's confirm stays reachable without scrolling. */
class FundsEditorKeyboardTest {
    @get:Rule val compose = createComposeRule()
    @get:Rule val keyboard = RealKeyboard()
    private val screen = FundsEditorDriver(compose)

    @After
    fun close() = screen.close()

    @Test
    fun incomeAmountKeepsConfirmAboveTheKeyboard() = with(screen) {
        show()
        openAccount("bank")
        compose.onNodeWithText(text(R.string.funds_record_income)).performClick()
        awaitEditor("income")
        val amount = field("${text(R.string.funds_income_received)}（CNY）")
        amount.performTouchInput { click() }
        amount.performTextInput("8650.00")
        keyboard.assertActionAboveKeyboard(compose, text(R.string.funds_confirm_save), "funds-editor-income-keyboard")
    }

    @Test
    fun repaymentPrincipalKeepsConfirmAboveTheKeyboardInMidnight() = with(screen) {
        show(AppSkin.Midnight)
        openAccount("huabei")
        compose.onNodeWithText(text(R.string.funds_record_actual_repayment)).performClick()
        awaitEditor("repay")
        compose.onNodeWithText(text(R.string.funds_choose_payer)).performScrollTo().performClick()
        compose.onNodeWithText("招商银行 · CNY").performClick()
        val principal = field(text(R.string.funds_principal, "CNY"))
        principal.performScrollTo().performTouchInput { click() }
        principal.performTextInput("37.90")
        keyboard.assertActionAboveKeyboard(compose, text(R.string.funds_confirm_save), "funds-editor-repay-keyboard-midnight")
    }
}

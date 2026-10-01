package com.ticketbox.ui.screens

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.click
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.ui.RealKeyboard
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class ManualExpenseDefaultChangeTest {
    @get:Rule val compose = createComposeRule()
    @get:Rule val keyboard = RealKeyboard()
    private val context = ApplicationProvider.getApplicationContext<Context>()

    @Test
    fun existingRawDraftKeepsCnyWhileTheNextTaskStartsWithJpy() {
        val defaultCurrency = mutableStateOf(CurrencyCode.CNY)
        val visible = mutableStateOf(true)
        val submitted = mutableListOf<ExpenseDraft>()
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                if (visible.value) ManualExpenseSheet(
                    state = ManualExpenseSheetState(emptyList(), saving = false, initialCurrency = defaultCurrency.value),
                    actions = ManualExpenseSheetActions(onCreate = { submitted += it }, onDismiss = {}),
                )
            }
        }
        enterAmount()
        compose.runOnIdle { defaultCurrency.value = CurrencyCode.JPY }
        save("manual-original-cny-keyboard")
        val original = compose.runOnIdle {
            assertEquals(1, submitted.size)
            submitted.single()
        }
        assertEquals(CurrencyCode.CNY, original.originalCurrencyCode)
        assertEquals(1200L, original.originalAmountMinor)
        assertEquals(CurrencyCode.CNY, original.ledgerHomeCurrency)

        compose.runOnIdle { visible.value = false }
        compose.waitForIdle()
        compose.runOnIdle { visible.value = true }
        enterAmount()
        save("manual-next-jpy-keyboard")
        val next = compose.runOnIdle {
            assertEquals(2, submitted.size)
            submitted.last()
        }
        assertEquals(CurrencyCode.JPY, next.originalCurrencyCode)
        assertEquals(12L, next.originalAmountMinor)
        assertEquals(CurrencyCode.JPY, next.ledgerHomeCurrency)
    }

    private fun enterAmount() {
        val amount = compose.onAllNodes(hasSetTextAction())[0]
        amount.performScrollTo().performTouchInput { click() }
        amount.performTextInput("12")
        amount.assertTextEquals("12")
    }

    private fun save(captureName: String) {
        val label = context.getString(R.string.ledger_manual_save_button)
        keyboard.assertActionAboveKeyboard(compose, label, captureName)
        compose.onNodeWithText(label).performTouchInput { click() }
        compose.waitForIdle()
    }
}

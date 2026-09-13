package com.ticketbox.ui.screens

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertTextEquals
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.closeSoftKeyboard
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class ManualExpenseDefaultChangeTest {
    @get:Rule val compose = createComposeRule()
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
        save()
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
        save()
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
        amount.performTextInput("12")
        amount.assertTextEquals("12")
        closeSoftKeyboard()
        compose.waitForIdle()
    }

    private fun save() {
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        compose.waitForIdle()
    }
}

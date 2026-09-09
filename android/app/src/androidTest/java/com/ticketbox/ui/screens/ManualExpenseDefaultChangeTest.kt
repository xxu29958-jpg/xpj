package com.ticketbox.ui.screens

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.test.core.app.ApplicationProvider
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
        compose.onAllNodes(hasSetTextAction())[0].performTextInput("12")
        compose.runOnIdle { defaultCurrency.value = CurrencyCode.JPY }
        save()
        assertEquals(CurrencyCode.CNY, submitted.single().originalCurrencyCode)
        assertEquals(1200L, submitted.single().originalAmountMinor)
        assertEquals(CurrencyCode.CNY, submitted.single().ledgerHomeCurrency)

        compose.runOnIdle { visible.value = false }
        compose.waitForIdle()
        compose.runOnIdle { visible.value = true }
        compose.onAllNodes(hasSetTextAction())[0].performTextInput("12")
        save()
        assertEquals(CurrencyCode.JPY, submitted.last().originalCurrencyCode)
        assertEquals(12L, submitted.last().originalAmountMinor)
        assertEquals(CurrencyCode.JPY, submitted.last().ledgerHomeCurrency)
    }

    private fun save() {
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performScrollTo().performClick()
        compose.waitForIdle()
    }
}

package com.ticketbox.ui.screens

import android.content.Context
import androidx.compose.runtime.mutableStateOf
import com.ticketbox.ui.assertEditableTextEquals
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
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ExpenseSourceValues
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.ui.RealKeyboard
import com.ticketbox.viewmodel.LedgerUiState
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
        val state = mutableStateOf(LedgerUiState(monthFilter = "", syncedInCurrentSession = true))
        val submitted = mutableListOf<ExpenseDraft>()
        val receipt = (ledgerHeaderConfirmedRow() as ConfirmedStreamItem.ExpenseRow).root
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                LedgerScreen(state = state.value, actions = LedgerScreenActions(
                    onPrepareManualCreate = { defaultCurrency.value },
                    onManualCreate = { draft ->
                        submitted += draft
                        val currency = requireNotNull(draft.originalCurrencyCode)
                        state.value = state.value.copy(manualCreateResult = receipt.copy(
                            id = submitted.size.toLong(), publicId = "manual-${submitted.size}",
                            amountCents = draft.originalAmountMinor, homeAmountCents = draft.originalAmountMinor,
                            homeCurrency = currency, homeCurrencyCode = currency.storageKey,
                            originalCurrency = currency, originalCurrencyCode = currency,
                            originalAmountMinor = draft.originalAmountMinor, source = ExpenseSourceValues.MANUAL_ENTRY,
                        ))
                    },
                    onManualCreateSettled = { state.value = state.value.copy(manualCreateResult = null) },
                ))
            }
        }
        compose.onNodeWithText("记一笔").performTouchInput { click() }
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

        // Let the real receipt effect close the first task. Start the next one
        // through the ledger entry, rather than replacing dialog windows from a
        // test-only visibility variable while the OS input target is changing.
        compose.onNodeWithText(context.getString(R.string.ledger_manual_sheet_title)).assertDoesNotExist()
        keyboard.dismissAndWait(compose)
        compose.onNodeWithText("记一笔").performTouchInput { click() }
        enterAmount()
        save("manual-next-jpy-keyboard")
        val next = compose.runOnIdle {
            assertEquals(2, submitted.size)
            submitted.last()
        }
        assertEquals(CurrencyCode.JPY, next.originalCurrencyCode)
        assertEquals(12L, next.originalAmountMinor)
        assertEquals(CurrencyCode.JPY, next.ledgerHomeCurrency)
        // The real LedgerScreen closes after successful creation. Finish that
        // same exit before the rule tears down the host and restores IME settings.
        compose.onNodeWithText(context.getString(R.string.ledger_manual_sheet_title)).assertDoesNotExist()
        keyboard.dismissAndWait(compose)
    }

    private fun enterAmount() {
        val amount = compose.onAllNodes(hasSetTextAction())[0]
        amount.performScrollTo().performTouchInput { click() }
        amount.performTextInput("12")
        amount.assertEditableTextEquals("12")
    }

    private fun save(captureName: String) {
        val label = context.getString(R.string.ledger_manual_save_button)
        keyboard.assertActionAboveKeyboard(compose, label, captureName)
        compose.onNodeWithText(label).performTouchInput { click() }
        compose.waitForIdle()
    }
}

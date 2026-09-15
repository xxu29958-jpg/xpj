package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeDown
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.screens.ManualExpenseSheetActions
import com.ticketbox.ui.screens.ManualExpenseSheetInitials
import com.ticketbox.ui.screens.ManualExpenseSheetState
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Payment sheet reuses AppBusyGuardedSheet: saving swipe cannot hide retry. */
class RecurringPaymentSheetGuardTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()

    @Test fun savingSwipeDownKeepsTheSheetVisible() {
        var dismissed = false
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                RecurringPaymentSheet(
                    RecurringPaymentSheetBody(
                        state = ManualExpenseSheetState(
                            categories = emptyList(),
                            saving = true,
                            initialCurrency = CurrencyCode.CNY,
                        ),
                        actions = ManualExpenseSheetActions(
                            onCreate = {},
                            onDismiss = { dismissed = true },
                        ),
                        initials = ManualExpenseSheetInitials(merchant = "房租"),
                    ),
                    rememberSaveableStateHolder(),
                    "period-ref",
                    onDraftChange = {},
                )
            }
        }
        compose.waitForIdle()
        val title = context.getString(R.string.ledger_manual_sheet_title)
        compose.onNodeWithText(title).assertIsDisplayed()
        repeat(3) {
            compose.onNodeWithText(title).performTouchInput { swipeDown() }
            compose.waitForIdle()
        }
        compose.onNodeWithText(title).assertIsDisplayed()
        assertTrue(!dismissed)
    }
}

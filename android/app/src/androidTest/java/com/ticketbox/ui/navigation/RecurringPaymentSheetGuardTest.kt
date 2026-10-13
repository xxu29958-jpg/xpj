package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.hasScrollAction
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.swipeDown
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.screens.ManualExpenseSheetActions
import com.ticketbox.ui.screens.ManualExpenseSheetInitials
import com.ticketbox.ui.screens.ManualExpenseSheetState
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.ui.saveConsumerArtPreview
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Payment sheet reuses AppBusyGuardedSheet: saving swipe cannot hide retry. */
class RecurringPaymentSheetGuardTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val skin = if (InstrumentationRegistry.getArguments().getString("captureSkin") == "midnight")
        AppSkin.Midnight else AppSkin.Paper

    @Test fun savingSwipeDownKeepsTheSheetVisible() {
        var dismissed = false
        compose.setContent {
            TicketboxTheme(skin = skin) {
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
        capture("recurring-payment-saving")
        repeat(3) {
            compose.onNodeWithText(title).performTouchInput { swipeDown() }
            compose.waitForIdle()
        }
        compose.onNodeWithText(title).assertIsDisplayed()
        assertTrue(!dismissed)
    }

    @Test fun readOnlySheetSwipeIsNotTreatedAsSubmitting() {
        var dismissed = false
        compose.setContent {
            TicketboxTheme(skin = skin) {
                RecurringPaymentSheet(
                    RecurringPaymentSheetBody(
                        state = ManualExpenseSheetState(
                            categories = emptyList(),
                            saving = false,
                            editable = false,
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
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).assertIsNotEnabled()
        compose.onNodeWithText("房租").assertIsNotEnabled()
        capture("recurring-payment-readonly")
        compose.onNodeWithText(title).performTouchInput { swipeDown() }
        compose.waitForIdle()
        assertTrue(dismissed)
    }

    private fun capture(name: String) {
        saveConsumerArtPreview(name, compose.onNode(hasScrollAction())
            .captureToImage().asAndroidBitmap())
        saveConsumerArtPreview("$name-window", requireNotNull(
            InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
    }
}

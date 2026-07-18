package com.ticketbox.ui.screens.settings

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollTo
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Rule
import org.junit.Test

class BackgroundPreviewScreenContractTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun receiptConfirmationIsAnExplicitlyDisabledVisualSample() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val confirmText = context.getString(R.string.background_preview_edit_confirm_button)
        val sampleNotice = context.getString(R.string.background_preview_edit_sample_notice)
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Paper) {
                BackgroundPreviewScreen(
                    initialSettings = BackgroundSettings(),
                    currentSkin = AppSkin.Paper,
                    title = "纸感",
                    onBack = {},
                    onApply = {},
                )
            }
        }

        composeRule.onNodeWithText(confirmText)
            .performScrollTo()
            .assertIsDisplayed()
            .assertIsNotEnabled()
        composeRule.onNodeWithText(sampleNotice)
            .performScrollTo()
            .assertIsDisplayed()
    }
}

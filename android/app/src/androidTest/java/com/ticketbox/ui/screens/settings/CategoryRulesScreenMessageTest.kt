package com.ticketbox.ui.screens.settings

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Rule
import org.junit.Test

/**
 * Pins the VM→Screen message channel of 分类规则:
 * CategoryRulesViewModel writes `uiState.message` for every operation, but the
 * screen used to have no `message` parameter at all, so success/failure
 * feedback never rendered. The screen must surface a non-blank message and
 * render nothing for null.
 *
 * UI/UX 批 11 moved the feedback from the page tail into the page-header status
 * slot (AppStatusBanner), so it appears where the user is already looking
 * instead of below a scroll. The banner sits between the header and content,
 * so a non-blank message is displayed without scrolling.
 */
class CategoryRulesScreenMessageTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun viewModelMessageRendersInHeaderStatusSlot() {
        setScreenContent(message = UiText.Raw("规则保存失败"))

        composeRule.onNodeWithText("规则保存失败").assertIsDisplayed()
    }

    @Test
    fun nullMessageRendersNoStatusText() {
        setScreenContent(message = null)

        composeRule.onNodeWithText("规则保存失败").assertDoesNotExist()
    }

    private fun setScreenContent(message: UiText?) {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                CategoryRulesScreen(
                    rules = emptyList(),
                    busy = false,
                    readOnly = false,
                    message = message,
                    onBack = {},
                    onCreateRule = { _, _, _ -> },
                    onUpdateRule = { _, _, _, _ -> },
                    onToggleRule = {},
                    onDeleteRule = {},
                    applications = emptyList(),
                    confirmedPreview = null,
                    onPreviewApplyConfirmedRules = {},
                    onConfirmApplyConfirmedRules = {},
                    onRollbackRuleApplication = {},
                )
            }
        }
    }
}

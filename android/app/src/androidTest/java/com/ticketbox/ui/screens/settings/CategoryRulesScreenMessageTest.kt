package com.ticketbox.ui.screens.settings

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollTo
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Rule
import org.junit.Test

/**
 * Pins the (previously dead) VM→Screen message channel of 分类规则:
 * CategoryRulesViewModel writes `uiState.message` for every operation, but the
 * screen used to have no `message` parameter at all, so success/failure
 * feedback never rendered. The screen must surface a non-blank message at the
 * page tail (mirroring MerchantAliasesScreen) and render nothing for null.
 */
class CategoryRulesScreenMessageTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun viewModelMessageRendersAtPageTail() {
        setScreenContent(message = UiText.Raw("规则保存失败"))

        composeRule.onNodeWithText("规则保存失败").performScrollTo().assertIsDisplayed()
    }

    @Test
    fun nullMessageRendersNoTailText() {
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

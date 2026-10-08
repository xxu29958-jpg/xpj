package com.ticketbox.ui.screens.settings

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollTo
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.ui.saveConsumerArtPreview
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

    @Test
    fun historySeparatesOriginalUpdatesFromRetainedRollbackCounts() {
        val original = RuleApplicationBatch("batch-first", "rollback_partial", 7, 3,
            "2026-10-07T10:00:00Z", "2026-10-07T11:00:00Z", mapOf("rolled_back" to 2, "skipped" to 1))
        setScreenContent(null, listOf(original, original.copy(publicId = "legacy", changeCounts = null)))
        composeRule.onNodeWithText("已恢复 2 笔 · 跳过 1 笔").performScrollTo().assertIsDisplayed()
        composeRule.waitForIdle()
        InstrumentationRegistry.getInstrumentation().uiAutomation.waitForIdle(250, 5_000)
        saveConsumerArtPreview("rule-history-outcomes", requireNotNull(
            InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        composeRule.onNodeWithText("此服务端未提供回退明细。").performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText("回退", substring = false).assertDoesNotExist()
    }

    private fun setScreenContent(message: UiText?, history: List<RuleApplicationBatch> = emptyList()) {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                CategoryRulesScreen(
                    state = categoryRulesScreenWithHeaderMessage(message, history),
                    actions = categoryRulesActionsUnusedByMessageSlot(),
                )
            }
        }
    }

    private fun categoryRulesScreenWithHeaderMessage(message: UiText?, history: List<RuleApplicationBatch>): CategoryRulesScreenState =
        CategoryRulesScreenState(
            rules = CategoryRulesRuleListState(
                rules = emptyList(),
                loading = false,
            ),
            interaction = CategoryRulesInteractionState(
                busy = false,
                readOnly = false,
            ),
            status = CategoryRulesStatusState(
                message = message,
                messageTone = MessageTone.Danger,
            ),
            applications = CategoryRulesApplicationState(
                history = history,
                loading = false,
                confirmedPreview = null,
            ),
            undoableRule = null,
        )

    private fun categoryRulesActionsUnusedByMessageSlot(): CategoryRulesScreenActions =
        CategoryRulesScreenActions(
            onBack = {},
            definitions = CategoryRuleDefinitionActions({}, {}, {}, { _, _ -> }, {}, {}, {}),
            rules = CategoryRulesRuleActions(
                onToggle = {},
                onDelete = {},
                onRecoverSubmission = { _, _ -> },
                onReload = {},
            ),
            applications = CategoryRulesApplicationActions(
                onPreviewApplyConfirmedRules = {},
                onConfirmApplyConfirmedRules = {},
                onRollbackRuleApplication = {},
                onReload = {},
            ),
            undo = CategoryRulesUndoActions(
                onUndoDelete = {},
                onDismiss = {},
            ),
        )
}

package com.ticketbox.ui.screens.settings

import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.espresso.Espresso.pressBack
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.domain.model.RuleApplicationBatch
import com.ticketbox.domain.model.RuleApplyConfirmedResult
import com.ticketbox.domain.model.RuleApplyPreviewItem
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

    @Test fun previewIsASeparateReadOnlyTaskWithActualSkipReasonsAndSamples() {
        val preview = RuleApplyConfirmedResult(true, 10, 8,
            listOf(RuleApplyPreviewItem(1, "街角小馆", "其他", "餐饮", "小馆", "matched")),
            2, 1, 1, 0, true, 500, "read-only-preview")
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.valueOf(InstrumentationRegistry.getArguments().getString("ruleSkin") ?: "Paper")) {
                CategoryRulesScreen(categoryRulesScreenWithHeaderMessage(null, emptyList()).copy(
                    interaction = CategoryRulesInteractionState(false, true),
                    applications = CategoryRulesApplicationState(emptyList(), false, preview)),
                    categoryRulesActionsUnusedByMessageSlot())
            }
        }
        capture("rule-directory")
        composeRule.onNodeWithText("预览已确认账单").performScrollTo().performClick()
        composeRule.onNodeWithText("这次会改哪些账单").assertIsDisplayed()
        capture("rule-preview-top")
        composeRule.onNodeWithText("规则列表").assertDoesNotExist()
        composeRule.onNodeWithText("保留已有分类").performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText("2 笔分类不覆盖；这些记录未纳入待更新扫描。").performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText("未命中 1 笔 · 分类不变 1 笔").performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText("展开 1 笔样本").performScrollTo().performClick()
        composeRule.onNodeWithText("街角小馆").performScrollTo().assertIsDisplayed()
        capture("rule-preview-skips")
        composeRule.onNodeWithText("确认应用").performScrollTo().assertIsNotEnabled()
        pressBack()
        composeRule.onNodeWithText("规则列表").performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText("规则应用记录").performScrollTo().performClick()
        composeRule.onNodeWithText("还没有应用记录。").performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText("返回规则列表").performScrollTo().performClick()
        composeRule.onNodeWithText("规则列表").performScrollTo().assertIsDisplayed()
    }

    @Test
    fun historySeparatesOriginalUpdatesFromRetainedRollbackCounts() {
        val original = RuleApplicationBatch("batch-first", "rollback_partial", 7, 3,
            "2026-10-07T10:00:00Z", "2026-10-07T11:00:00Z", mapOf("rolled_back" to 2, "skipped" to 1))
        setScreenContent(null, listOf(original, original.copy(publicId = "legacy", changeCounts = null)))
        composeRule.onNodeWithText("规则应用记录").performScrollTo().performClick()
        composeRule.onNodeWithText("已恢复 2 笔 · 跳过 1 笔").performScrollTo().assertIsDisplayed()
        composeRule.waitForIdle()
        InstrumentationRegistry.getInstrumentation().uiAutomation.waitForIdle(250, 5_000)
        saveConsumerArtPreview("rule-history-outcomes", requireNotNull(
            InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
        composeRule.onNodeWithText("此服务端未提供回退明细。").performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText("回退", substring = false).assertDoesNotExist()
    }

    private fun capture(name: String) {
        composeRule.waitForIdle()
        val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
        automation.waitForIdle(250, 5_000)
        saveConsumerArtPreview(name, requireNotNull(automation.takeScreenshot()))
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

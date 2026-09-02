package com.ticketbox.ui.screens.settings

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Rule
import org.junit.Test

/**
 * W2-B 资料库迁移回归：分类规则的只读显示门。
 * 旧 CategoryRuleCreateSection 先 `if (readOnly) return`——readOnly 时不渲染添加入口，
 * 激活中的草稿也不留下可提交编辑器（draft 状态本身保留，只是不渲染；VM 仍会拒写）。
 * 迁移把 create 并入规则列表段头后，这道门必须同时约束入口按钮与编辑器渲染。
 */
class CategoryRulesReadOnlyGateTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun readOnlyHidesCreateEntryAndShowsNote() {
        setRulesScreen(readOnly = true)

        composeRule.onNodeWithText(ADD_RULE).assertDoesNotExist()
        composeRule.onNodeWithText(READONLY_NOTE).assertIsDisplayed()
    }

    @Test
    fun writerCanOpenEditorFromListHeader() {
        setRulesScreen(readOnly = false)

        composeRule.onNodeWithText(ADD_RULE).assertIsDisplayed().performClick()
        composeRule.onNodeWithText(EDITOR_KEYWORD_LABEL).assertIsDisplayed()
    }

    @Test
    fun activeDraftEditorHidesWhenReadOnlyFlips() {
        val readOnly = mutableStateOf(false)
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                CategoryRulesScreen(
                    state = rulesState(readOnly = readOnly.value),
                    actions = unusedActions(),
                )
            }
        }

        composeRule.onNodeWithText(ADD_RULE).performClick()
        composeRule.onNodeWithText(EDITOR_KEYWORD_LABEL).assertIsDisplayed()

        readOnly.value = true

        composeRule.onNodeWithText(EDITOR_KEYWORD_LABEL).assertDoesNotExist()
        composeRule.onNodeWithText(ADD_RULE).assertDoesNotExist()
    }

    private fun setRulesScreen(readOnly: Boolean) {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                CategoryRulesScreen(
                    state = rulesState(readOnly = readOnly),
                    actions = unusedActions(),
                )
            }
        }
    }

    private fun rulesState(readOnly: Boolean): CategoryRulesScreenState =
        CategoryRulesScreenState(
            rules = CategoryRulesRuleListState(rules = emptyList(), loading = false),
            interaction = CategoryRulesInteractionState(busy = false, readOnly = readOnly),
            status = CategoryRulesStatusState(message = null, messageTone = MessageTone.Neutral),
            applications = CategoryRulesApplicationState(
                history = emptyList(),
                loading = false,
                confirmedPreview = null,
            ),
            undoableRule = null,
        )

    private fun unusedActions(): CategoryRulesScreenActions =
        CategoryRulesScreenActions(
            onBack = {},
            rules = CategoryRulesRuleActions(
                onCreate = { _, _, _ -> },
                onUpdate = { _, _, _, _ -> },
                onToggle = {},
                onDelete = {},
            ),
            applications = CategoryRulesApplicationActions(
                onPreviewApplyConfirmedRules = {},
                onConfirmApplyConfirmedRules = {},
                onRollbackRuleApplication = {},
            ),
            undo = CategoryRulesUndoActions(onUndoDelete = {}, onDismiss = {}),
        )

    private companion object {
        const val ADD_RULE = "添加规则"
        const val EDITOR_KEYWORD_LABEL = "商家关键词"
        const val READONLY_NOTE = "当前角色为只读，无法修改账本。"
    }
}

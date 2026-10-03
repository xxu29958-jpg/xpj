package com.ticketbox.ui.screens.settings

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.LedgerSummary
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.LedgerRenameDraft
import com.ticketbox.viewmodel.LedgerSwitcherUiState
import org.junit.Rule
import org.junit.Test

class LedgerRenameDialogTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun conflictRetainsEditableInputAndSaveWaitsForRefreshedPermission() {
        val ledger = LedgerSummary("ledger", "家庭", "owner", true, null, null)
        val state = mutableStateOf(LedgerSwitcherUiState(rename = LedgerRenameDraft(ledger)))
        var saves = 0
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                LedgerRenameDialog(state.value,
                    onNameChange = { state.value = state.value.copy(rename = state.value.rename?.copy(name = it)) },
                    onDismiss = {},
                    onSave = { saves++ },
                    onRefresh = { state.value = state.value.copy(rename = state.value.rename?.copy(fresh = true)) })
            }
        }
        compose.onNodeWithText("账本名称").performTextReplacement("我的输入")
        compose.runOnIdle {
            state.value = state.value.copy(rename = state.value.rename?.copy(ledger = ledger.copy(name = "电脑改名"), fresh = false),
                message = UiText.raw("请刷新当前名称。"), messageTone = MessageTone.Danger)
        }
        compose.onNodeWithText("账本名称").assertTextContains("我的输入")
        compose.onNodeWithText("当前名称：电脑改名").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("保存名称").assertIsNotEnabled()
        compose.onNodeWithText("刷新列表").performScrollTo().performClick()
        compose.onNodeWithText("保存名称").performClick()
        compose.runOnIdle { check(saves == 1 && state.value.rename?.name == "我的输入") }
    }
}

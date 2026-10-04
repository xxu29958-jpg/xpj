package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertEditableTextEquals
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.LedgerSummary
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.PlatformFontScale
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.LedgerListLoadState
import com.ticketbox.viewmodel.LedgerSwitcherUiState
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class LedgerDirectoryPageTest {
    @get:Rule val compose = createComposeRule()
    private var state by mutableStateOf(LedgerSwitcherUiState(ledgers = listOf(
        LedgerSummary("personal", "个人账本", "owner", true), LedgerSummary("family", "家庭账本", "viewer", false)),
        listLoadState = LedgerListLoadState.Loaded))
    private var skin by mutableStateOf(AppSkin.Paper)
    private var scale by mutableStateOf(1f)
    private var active by mutableStateOf("personal")
    private val switches = mutableListOf<String>()
    private val creates = mutableListOf<String>()
    private val renames = mutableListOf<String>()
    private var joins = 0
    private var completeCreate: (() -> Unit)? = null

    @Test fun directoryKeepsSwitchRenameAndFailedCreateInput() {
        show()
        capture("ledgers-paper")
        compose.onNodeWithText("家庭账本").performScrollTo().performClick()
        compose.runOnIdle { assertEquals(listOf("family"), switches); active = "family" }
        compose.onNodeWithText("新账本名称").performScrollTo().performTextReplacement("旅行账本")
        compose.onNodeWithText("创建账本").assertIsDisplayed().performClick()
        compose.runOnIdle {
            assertEquals(listOf("旅行账本"), creates)
            state = state.copy(loading = true)
        }
        compose.onNodeWithText("创建账本").assertIsNotEnabled()
        compose.runOnIdle { state = state.copy(loading = false, message = UiText.Raw("创建暂未完成，请重试。"), messageTone = MessageTone.Danger) }
        compose.onNodeWithText("新账本名称").performScrollTo().assertTextContains("旅行账本")
        capture("ledgers-create-failure")
        compose.onNodeWithText("创建账本").performClick()
        compose.runOnIdle { assertEquals(listOf("旅行账本", "旅行账本"), creates); completeCreate?.invoke() }
        compose.onNodeWithText("新账本名称").assertEditableTextEquals("")
        compose.onNodeWithText("账本管理").performScrollTo().performClick()
        compose.onNodeWithText("修改账本名称").performScrollTo().performClick()
        compose.runOnIdle { assertEquals(listOf("personal"), renames) }
        compose.onNodeWithText("加入家庭账本").performScrollTo().performClick()
        compose.runOnIdle { assertEquals(1, joins) }
        compose.onNodeWithText("账本管理").performScrollTo().performClick()
        compose.runOnIdle { scale = 1.8f; skin = AppSkin.Midnight }
        compose.onNodeWithText("我的账本").performScrollTo()
        capture("ledgers-midnight-large")
    }

    private fun show() = compose.setContent {
        PlatformFontScale(scale) {
            TicketboxTheme(skin = skin) {
                Box(Modifier.fillMaxSize().testTag("ledger-directory")) {
                    LedgerDirectoryPage(state, active, LedgerDirectoryActions(onBack = {}, onJoin = { joins++ }, onRefresh = {},
                        onSwitch = { switches += it }, onRename = { renames += it.ledgerId },
                        onCreate = { name, completed -> creates += name; completeCreate = completed }, onNameRequired = {}))
                }
            }
        }
    }

    private fun capture(name: String) = saveConsumerArtPreview(name,
        compose.onNodeWithTag("ledger-directory").captureToImage().asAndroidBitmap())
}

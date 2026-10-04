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
import com.ticketbox.domain.model.InvitationPreview
import com.ticketbox.domain.model.InvitationSessionTarget
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.PlatformFontScale
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.screens.ServerUrlEntryConfig
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.JoinFamilyLedgerUiState
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class JoinFamilyLedgerPageTest {
    @get:Rule val compose = createComposeRule()
    private var state by mutableStateOf(JoinFamilyLedgerUiState(serverUrl = "https://ledger.example.test"))
    private var binding by mutableStateOf(JoinCurrentBinding("我", "个人账本", "拥有者", unbound = true, backLabel = "我的账本"))
    private var skin by mutableStateOf(AppSkin.Paper)
    private var scale by mutableStateOf(1f)
    private var previews = 0
    private var accepts = 0
    private var browserOpens = 0
    private val invitation = InvitationPreview("service", "generation", "family", "家庭账本", "member", "2026-10-08T12:00:00Z")

    @Test fun unboundInvitationRequiresPreviewAndNameAndRetainsFailedInput() {
        show()
        capture("join-paper")
        compose.onNodeWithText("预览加入信息").assertIsNotEnabled()
        compose.onNodeWithText("邀请").performScrollTo().performTextReplacement("test-invitation")
        compose.onNodeWithText("预览加入信息").assertIsDisplayed().performClick()
        compose.runOnIdle { assertEquals(1, previews); assertEquals(0, accepts)
            state = state.copy(preview = invitation, target = InvitationSessionTarget.Unbound) }
        compose.onNodeWithText("加入账本").assertIsNotEnabled()
        compose.onNodeWithText("你的称呼").performScrollTo().performTextReplacement("新成员")
        compose.onNodeWithText("加入账本").performClick()
        compose.runOnIdle { assertEquals(1, accepts); state = state.copy(submitting = true) }
        compose.onNodeWithText("处理中…").assertIsNotEnabled()
        compose.runOnIdle { state = state.copy(submitting = false, error = UiText.Raw("加入暂未完成，请重试。")) }
        compose.onNodeWithText("你的称呼").performScrollTo().assertTextContains("新成员")
        compose.onNodeWithText("邀请").performScrollTo().assertTextContains("test-invitation")
        capture("join-failed-retained-input")
        compose.onNodeWithText("加入账本").performClick()
        compose.runOnIdle { assertEquals(2, accepts); assertEquals(0, browserOpens) }
    }

    @Test fun boundForeignInvitationOnlyOffersBrowserAndPreservesCurrentIdentity() {
        state = state.copy(sourceHost = "other.example.test", preview = invitation, target = InvitationSessionTarget.ForeignServer)
        binding = binding.copy(unbound = false)
        show()
        compose.onNodeWithText("加入账本").assertDoesNotExist()
        compose.onNodeWithText("你的称呼").assertDoesNotExist()
        compose.onNodeWithText("使用身份").performScrollTo().performClick()
        compose.onNodeWithText("将以“我”的当前成员身份加入，不会新建设备或覆盖待同步内容。").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("在浏览器中继续").assertIsDisplayed().performClick()
        compose.runOnIdle { assertEquals(0, accepts); assertEquals(0, previews); assertEquals(1, browserOpens) }
        capture("join-foreign-browser")
        compose.runOnIdle { scale = 1.8f; skin = AppSkin.Midnight }
        compose.onNodeWithText("加入家庭账本").performScrollTo()
        capture("join-midnight-large")
        compose.onNodeWithText("在浏览器中继续").assertIsDisplayed()
    }

    private fun show() = compose.setContent {
        PlatformFontScale(scale) {
            TicketboxTheme(skin = skin) {
                Box(Modifier.fillMaxSize().testTag("join-page")) {
                    JoinFamilyLedgerPage(state, binding, if (binding.unbound) ServerUrlEntryConfig(state.serverUrl, false) else null,
                        JoinInvitationActions(onBack = {}, onServerUrlChange = { state = state.copy(serverUrl = it) },
                            onInviteChange = { state = state.copy(invitationInput = it) }, onNameChange = { state = state.copy(accountName = it) },
                            onScan = {}, onPreview = { previews++ }, onAccept = { accepts++ }, onContinueInBrowser = { browserOpens++ }))
                }
            }
        }
    }

    private fun capture(name: String) = saveConsumerArtPreview(name,
        compose.onNodeWithTag("join-page").captureToImage().asAndroidBitmap())
}

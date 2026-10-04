package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.hasAnyAncestor
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.isDialog
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.text.TextLayoutResult
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.PlatformFontScale
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class SecurityPrivacyScreenTest {
    @get:Rule val compose = createComposeRule()

    @Test fun clearAndExitRequireTheirOwnConfirmationAndBusyCannotConfirm() {
        var busy by mutableStateOf(false)
        var message by mutableStateOf<String?>(null)
        var skin by mutableStateOf(AppSkin.Paper)
        var scale by mutableStateOf(1f)
        var clears = 0
        var exits = 0
        compose.setContent {
            PlatformFontScale(scale) {
                TicketboxTheme(skin = skin) {
                    Box(Modifier.fillMaxSize().testTag("security-page")) {
                        SecurityPrivacyScreen(onBack = {}, busy = busy,
                            onClearCache = { clears++; message = "副本暂未清除，请重试。" },
                            onBindingCleared = { exits++ },
                            status = { message?.let { AppStatusBanner(UiText.Raw(it), MessageTone.Danger) } })
                    }
                }
            }
        }
        capture("security-paper")
        val clear = compose.onNodeWithText("离线副本")
        clear.performScrollTo().performClick()
        compose.onNodeWithText("清除离线副本？").assertIsDisplayed()
        compose.onNodeWithText("取消").performClick()
        compose.runOnIdle { assertEquals(0, clears); assertEquals(0, exits) }
        clear.performClick()
        compose.onNode(hasText("清除副本") and hasAnyAncestor(isDialog())).performClick()
        compose.onNodeWithText("副本暂未清除，请重试。").performScrollTo().assertIsDisplayed()
        compose.runOnIdle { assertEquals(1, clears); assertEquals(0, exits) }
        val exit = compose.onNodeWithText("当前账本会话")
        exit.performScrollTo().performClick()
        compose.onNodeWithText("退出当前账本？").assertIsDisplayed()
        compose.runOnIdle { busy = true }
        compose.onNodeWithText("确定退出").assertIsNotEnabled()
        compose.onNodeWithText("取消").performClick()
        compose.runOnIdle { assertEquals(0, exits); busy = false; skin = AppSkin.Midnight; scale = 1.8f }
        exit.performScrollTo().performClick()
        val layouts = mutableListOf<TextLayoutResult>()
        compose.onNodeWithText("退出当前账本？").performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
        assertEquals(1.8f, layouts.single().layoutInput.density.fontScale, 0.001f)
        saveConsumerArtPreview("security-exit-midnight-large",
            compose.onNode(isDialog()).assertIsDisplayed().captureToImage().asAndroidBitmap())
        compose.onNodeWithText("确定退出").performClick()
        compose.runOnIdle { assertEquals(1, clears); assertEquals(1, exits) }
        compose.onNodeWithText("清除副本只清理", substring = true).performScrollTo().assertIsDisplayed()
        capture("security-device-actions-midnight-large")
    }

    private fun capture(name: String) = saveConsumerArtPreview(name,
        compose.onNodeWithTag("security-page").captureToImage().asAndroidBitmap())
}

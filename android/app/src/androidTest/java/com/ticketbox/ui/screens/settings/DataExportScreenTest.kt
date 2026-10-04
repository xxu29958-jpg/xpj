package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.isDialog
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.text.TextLayoutResult
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.LedgerSummary
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.PlatformFontScale
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.PortableExportStage
import com.ticketbox.viewmodel.PortableExportUiState
import com.ticketbox.viewmodel.SettingsUiState
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class DataExportScreenTest {
    @get:Rule val compose = createComposeRule()
    private var page by mutableStateOf(SettingsUiState())
    private var download by mutableStateOf(PortableExportUiState(
        ledgers = listOf(LedgerSummary("personal", "个人账本", "owner", true),
            LedgerSummary("family", "家庭账本", "member", false)), selectedLedgerId = "personal"))
    private var skin by mutableStateOf(AppSkin.Paper)
    private var scale by mutableStateOf(1f)
    private var refreshes = 0
    private var clears = 0
    private var saves = 0
    private var cancellations = 0

    @Test fun downloadKeepsAuthorizedSelectionProgressAndCancellation() {
        showPage()
        capture("data-paper")
        compose.onNodeWithText("下载完整数据").performScrollTo().performClick()
        compose.onNodeWithText("家庭账本").performScrollTo().performClick()
        compose.runOnIdle { assertEquals("family", download.selectedLedgerId) }
        compose.onNodeWithText("下载并保存完整数据包").performScrollTo().performClick()
        compose.runOnIdle { assertEquals(1, saves); assertEquals(0, clears); download = download.copy(stage = PortableExportStage.Downloading, bytesWritten = 2048) }
        compose.onNodeWithText("已写入 2 KB").performScrollTo().assertIsDisplayed()
        capture("data-downloading")
        compose.onNodeWithText("取消").performScrollTo().performClick()
        compose.onNodeWithText("下载已取消").performScrollTo().assertIsDisplayed()
        compose.runOnIdle { assertEquals(1, cancellations); assertEquals(0, clears) }
        compose.runOnIdle { download = download.copy(ledgers = emptyList(), selectedLedgerId = null,
            message = UiText.Raw("服务器暂时不可用"), tone = MessageTone.Danger) }
        compose.onNodeWithText("服务器暂时不可用").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("当前账户没有可下载的账本。").assertDoesNotExist()
        capture("data-download-failure")
    }

    @Test fun refreshAndClearRemainSeparateIncludingBusyConfirmation() {
        showPage()
        compose.onNodeWithText("重新读取账本").performScrollTo().performClick()
        compose.runOnIdle { assertEquals(1, refreshes); assertEquals(0, clears); assertEquals(0, saves) }
        compose.onNodeWithText("清理离线副本").performScrollTo().performClick()
        compose.runOnIdle { page = page.copy(busy = true) }
        compose.onNodeWithText("清除副本").assertIsNotEnabled()
        compose.onNodeWithText("取消").performClick()
        compose.runOnIdle { assertEquals(0, clears); page = page.copy(busy = false); skin = AppSkin.Midnight; scale = 1.8f }
        compose.onNodeWithText("清理离线副本").performScrollTo().performClick()
        val layouts = mutableListOf<TextLayoutResult>()
        compose.onNodeWithText("清除离线副本？").performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
        assertEquals(1.8f, layouts.single().layoutInput.density.fontScale, 0.001f)
        saveConsumerArtPreview("data-clear-midnight-large", compose.onNode(isDialog()).captureToImage().asAndroidBitmap())
        compose.onNodeWithText("清除副本").performClick()
        compose.onNodeWithText("副本暂未清除，请重试。").performScrollTo().assertIsDisplayed()
        compose.runOnIdle { assertEquals(1, clears); assertEquals(1, refreshes); assertEquals(0, saves) }
        compose.onNodeWithText("带走与保留数据").performScrollTo()
        capture("data-midnight-large")
    }

    private fun showPage() = compose.setContent {
        PlatformFontScale(scale) {
            TicketboxTheme(skin = skin) {
                Box(Modifier.fillMaxSize().testTag("data-page")) {
                    DataExportScreen(page, onBack = {}, onSync = { refreshes++ },
                        onClearCache = { clears++; page = page.copy(message = UiText.Raw("副本暂未清除，请重试。"), messageTone = MessageTone.Danger) }) {
                        PortableExportPanel(download, onSelect = { download = download.copy(selectedLedgerId = it) },
                            onSave = { saves++; download = download.copy(stage = PortableExportStage.ChoosingLocation) },
                            onCancel = { cancellations++; download = download.copy(stage = PortableExportStage.Idle, message = UiText.Raw("下载已取消")) },
                            onRefresh = {})
                    }
                }
            }
        }
    }

    private fun capture(name: String) = saveConsumerArtPreview(name,
        compose.onNodeWithTag("data-page").captureToImage().asAndroidBitmap())
}

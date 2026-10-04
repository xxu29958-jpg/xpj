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
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.ConnectionDiagnostics
import com.ticketbox.domain.model.DiagnosticCheck
import com.ticketbox.domain.model.DiagnosticCheckKind
import com.ticketbox.domain.model.DiagnosticStatus
import com.ticketbox.domain.model.ServerBackupHealth
import com.ticketbox.domain.model.ServerSettings
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.PlatformFontScale
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.SettingsUiState
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.assertEquals

class ConnectionDiagnosticsEntryTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun ordinaryMemberSeesTheFailedCheckAndNextStepWithoutInternalTools() {
        val nextStep = "请将手机应用与服务端更新到配套版本，再重新检测。"
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                ServerSettingsScreen(
                    state = ServerSettingsScreenState(
                        settings = SettingsUiState(
                            ledgerName = "家庭账本", role = "member",
                            diagnostics = ConnectionDiagnostics(listOf(
                                DiagnosticCheck(DiagnosticCheckKind.ConfirmedExpenses, DiagnosticStatus.Fail, nextStep, 1),
                            )),
                        ),
                        showAdvancedTools = false,
                    ),
                    actions = ServerSettingsScreenActions(
                        onBack = {}, onRunDiagnostics = {}, onCancelConnectionWork = {},
                        onRefreshServerSettings = {}, onSync = {}, onOpenSyncStatus = {},
                    ),
                )
            }
        }

        composeRule.onNodeWithText(nextStep).performScrollTo().assertIsDisplayed()
    }

    @Test fun connectionLayersKeepOriginalActionsAndDoNotTurnFailedReadsIntoHealthyStates() {
        var state by mutableStateOf(confirmedState())
        var skin by mutableStateOf(AppSkin.Paper)
        var scale by mutableStateOf(1f)
        var checks = 0
        var updates = 0
        var pending = 0
        composeRule.setContent {
            PlatformFontScale(scale) {
                TicketboxTheme(skin = skin) {
                    Box(Modifier.fillMaxSize().testTag("connection-page")) {
                        ServerSettingsScreen(ServerSettingsScreenState(state, showAdvancedTools = true),
                            ServerSettingsScreenActions({}, { checks++ }, {}, {}, { updates++ }, { pending++ }))
                    }
                }
            }
        }
        composeRule.onNodeWithText("可达").assertIsDisplayed()
        composeRule.onNodeWithText("有效").assertIsDisplayed()
        capture("connection-paper")
        composeRule.onNodeWithText("重新检查连接").performClick()
        composeRule.onNodeWithText("未发送操作").performScrollTo().performClick()
        composeRule.onNodeWithText("身份与权限").performScrollTo().performClick()
        composeRule.onNodeWithText("家庭共同账本").performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText("更新账本").performScrollTo().performClick()
        composeRule.runOnIdle { assertEquals(1, checks); assertEquals(1, pending); assertEquals(1, updates) }
        composeRule.onNodeWithText("最近发布").performScrollTo().performClick()
        composeRule.onNodeWithText("这里展示备份记录", substring = true).performScrollTo().assertIsDisplayed()
        capture("connection-backup-details")
        composeRule.runOnIdle {
            state = state.copy(serverSettingsFresh = false, backupHealth = null,
                backupError = UiText.Raw("备份记录暂时无法读取"),
                diagnostics = ConnectionDiagnostics(listOf(DiagnosticCheck(DiagnosticCheckKind.Auth,
                    DiagnosticStatus.Fail, "会话无法确认，请检查连接后重试。", 1))))
            skin = AppSkin.Midnight; scale = 1.8f
        }
        composeRule.onNodeWithText("会话无法确认，请检查连接后重试。").performScrollTo().assertIsDisplayed()
        composeRule.onNodeWithText("可达").assertDoesNotExist()
        composeRule.onNodeWithText("有效").assertDoesNotExist()
        composeRule.onNodeWithText("尚未发现备份发布记录。").assertDoesNotExist()
        composeRule.onNodeWithText("重新检查连接").assertIsDisplayed()
        composeRule.onNodeWithText("账本连接").performScrollTo()
        capture("connection-unconfirmed-midnight-large")
        composeRule.onNodeWithText("最近发布").performScrollTo().performClick()
        composeRule.onNodeWithText("备份记录暂时无法读取").performScrollTo().assertIsDisplayed()
        capture("connection-backup-read-failure")
    }

    private fun confirmedState(): SettingsUiState = SettingsUiState(
        serverSettingsFresh = true, serverUrl = "https://example.test", ledgerName = "家庭共同账本",
        serverSettings = ServerSettings(accountName = "账本拥有者", ledgerId = "ledger", ledgerName = "家庭共同账本",
            ledgerIsDefault = false, deviceName = "我的手机", role = "owner", status = "active", storageStatus = "normal",
            pendingCount = 3, confirmedCount = 12, rejectedCount = 0, suspectedDuplicateCount = 1,
            uploadStorageBytes = 1024, latestUploadAt = "2026-10-03T12:00:00Z"),
        backupHealth = ServerBackupHealth("2026-10-04T01:00:00Z", 3, false),
    )

    private fun capture(name: String) = saveConsumerArtPreview(name,
        composeRule.onNodeWithTag("connection-page").captureToImage().asAndroidBitmap())
}

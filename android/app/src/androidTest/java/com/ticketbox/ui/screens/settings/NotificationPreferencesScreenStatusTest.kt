package com.ticketbox.ui.screens.settings

import android.os.Build
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsOff
import androidx.compose.ui.test.assertIsOn
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.Density
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.NotificationPreferences
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Rule
import org.junit.Test
import org.junit.Assert.assertEquals

/**
 * UI/UX 批 11: NotificationPreferencesScreen used to render no on-screen
 * feedback at all — SettingsViewModel wrote `message` after a save, but the
 * screen ignored it, so "saved" was silent. The screen now exposes a page-header
 * status slot; the host fills it with an AppStatusBanner built from the VM's
 * message + tone.
 *
 * The screen exposes saved feedback and one named, operable control per preference.
 */
class NotificationPreferencesScreenStatusTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun savedStatusBannerIsVisible() {
        setScreenContent(
            status = {
                AppStatusBanner(
                    message = UiText.Raw("通知偏好已保存"),
                    tone = MessageTone.Success,
                )
            },
        )

        composeRule.onNodeWithText("通知偏好已保存").assertIsDisplayed()
    }

    @Test
    fun namedReminderRowChangesItsPreferenceExactlyOncePerActivation() {
        var preferences by mutableStateOf(NotificationPreferences())
        var saves = 0
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                NotificationPreferencesScreen(preferences, readOnly = false, onBack = {}, onSave = {
                    preferences = it
                    saves += 1
                })
            }
        }
        val reminder = composeRule.onNodeWithText("待确认提醒").performScrollTo()
        reminder.assertIsOff().performClick().assertIsOn()
        composeRule.runOnIdle {
            assertEquals(true, preferences.pendingDraftReminders)
            assertEquals(1, saves)
        }
        reminder.performClick().assertIsOff()
        composeRule.runOnIdle {
            assertEquals(false, preferences.pendingDraftReminders)
            assertEquals(2, saves)
        }
    }

    @Test
    fun storedCaptureWaitsForAuthorizationAndViewerCannotEnableIt() {
        var preferences by mutableStateOf(NotificationPreferences(autoCaptureEnabled = true))
        var listener by mutableStateOf(false)
        var notifications by mutableStateOf(false)
        var viewer by mutableStateOf(false)
        var skin by mutableStateOf(AppSkin.Paper)
        var scale by mutableStateOf(1f)
        var saves = 0
        var authorizations = 0
        var reminderPermissions = 0
        composeRule.setContent {
            CompositionLocalProvider(LocalDensity provides Density(LocalDensity.current.density, scale)) {
                TicketboxTheme(skin = skin) {
                    NotificationPreferencesContent(preferences, viewer,
                        NotificationSystemState(listener, notifications,
                            { reminderPermissions++ }, { authorizations++ }),
                        status = null, onBack = {}, onSave = { preferences = it; saves++ })
                }
            }
        }
        val capture = composeRule.onNodeWithText("解析支付通知")
        capture.assertIsOn()
        composeRule.onNodeWithText("开关已开启，等待系统授权；目前不会解析通知。").assertIsDisplayed()
        saveConsumerArtPreview("notifications-paper", composeRule.onRoot().captureToImage().asAndroidBitmap())
        composeRule.onNodeWithText("打开系统授权").performClick()
        composeRule.runOnIdle { assertEquals(1, authorizations); assertEquals(0, saves); listener = true }
        composeRule.onNodeWithText("查看系统授权").assertIsDisplayed()
        capture.performClick().assertIsOff().performClick().assertIsOn()
        for (title in listOf("待确认提醒", "大额提醒", "固定支出提醒", "预算超支提醒", "备份超龄提醒")) {
            composeRule.onNodeWithText(title).performScrollTo().assertIsOff().performClick().assertIsOn()
        }
        composeRule.runOnIdle {
            assertEquals(7, saves)
            assertEquals(if (Build.VERSION.SDK_INT >= 33) 5 else 0, reminderPermissions)
            assertEquals(NotificationPreferences(autoCaptureEnabled = true, pendingDraftReminders = true,
                largeAmountAlerts = true, recurringReminders = true, budgetOverspendAlerts = true,
                backupStaleAlerts = true), preferences)
        }
        composeRule.onNodeWithText("系统通知权限未开启，提醒不会展示。").performScrollTo().assertIsDisplayed()
        saveConsumerArtPreview("notifications-permission-missing", composeRule.onRoot().captureToImage().asAndroidBitmap())
        composeRule.runOnIdle { notifications = true; viewer = true; skin = AppSkin.Midnight; scale = 1.8f }
        composeRule.onNodeWithText("系统通知权限未开启，提醒不会展示。").assertDoesNotExist()
        capture.performScrollTo().assertIsOff().assertIsNotEnabled()
        composeRule.runOnIdle { assertEquals(7, saves); assertEquals(true, preferences.autoCaptureEnabled) }
        saveConsumerArtPreview("notifications-viewer-midnight-large", composeRule.onRoot().captureToImage().asAndroidBitmap())
        composeRule.onNodeWithText("采集只生成待核对记录").performScrollTo().assertIsDisplayed()
        saveConsumerArtPreview("notifications-privacy-large", composeRule.onRoot().captureToImage().asAndroidBitmap())
    }

    private fun setScreenContent(status: (@Composable () -> Unit)?) {
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                NotificationPreferencesScreen(
                    preferences = NotificationPreferences(),
                    readOnly = false,
                    status = status,
                    onBack = {},
                    onSave = {},
                )
            }
        }
    }
}

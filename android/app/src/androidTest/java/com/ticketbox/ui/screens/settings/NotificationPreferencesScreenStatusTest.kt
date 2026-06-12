package com.ticketbox.ui.screens.settings

import androidx.compose.runtime.Composable
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.NotificationPreferences
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Rule
import org.junit.Test

/**
 * UI/UX 批 11: NotificationPreferencesScreen used to render no on-screen
 * feedback at all — SettingsViewModel wrote `message` after a save, but the
 * screen ignored it, so "saved" was silent. The screen now exposes a page-header
 * status slot; the host fills it with an AppStatusBanner built from the VM's
 * message + tone.
 *
 * These pin that the slot actually surfaces feedback (the save confirmation is
 * visible) and that an empty slot stays silent.
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
    fun noStatusSlotRendersNoBanner() {
        setScreenContent(status = null)

        composeRule.onNodeWithText("通知偏好已保存").assertDoesNotExist()
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

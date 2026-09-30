package com.ticketbox.ui.screens.settings

import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsOff
import androidx.compose.ui.test.assertIsOn
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.NotificationPreferences
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppStatusBanner
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

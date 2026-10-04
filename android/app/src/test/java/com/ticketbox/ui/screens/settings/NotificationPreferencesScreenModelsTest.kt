package com.ticketbox.ui.screens.settings

import com.ticketbox.domain.model.NotificationPreferences
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class NotificationPreferencesScreenModelsTest {
    @Test
    fun summaryMarksAutoDraftReadOnlyBeforeStoredToggle() {
        val summary = notificationPreferencesSummary(
            preferences = NotificationPreferences(autoCaptureEnabled = true),
            readOnly = true,
            listenerAuthorized = true,
            systemNotificationsAllowed = true,
        )

        assertEquals(NotificationSettingState.ReadOnly, summary.autoDraftState)
        assertEquals(NotificationSettingState.AwaitingAuthorization, notificationPreferencesSummary(
            NotificationPreferences(autoCaptureEnabled = true), readOnly = false,
            listenerAuthorized = false, systemNotificationsAllowed = true,
        ).autoDraftState)
        assertEquals(NotificationSettingState.Enabled, notificationPreferencesSummary(
            NotificationPreferences(autoCaptureEnabled = true), readOnly = false,
            listenerAuthorized = true, systemNotificationsAllowed = false,
        ).autoDraftState)
        assertFalse(summary.reminderPermissionMismatch)
    }

    @Test
    fun summaryCountsEnabledRemindersAndPermissionMismatch() {
        val summary = notificationPreferencesSummary(
            preferences = NotificationPreferences(
                pendingDraftReminders = true,
                largeAmountAlerts = true,
                backupStaleAlerts = true,
            ),
            readOnly = false,
            listenerAuthorized = false,
            systemNotificationsAllowed = false,
        )

        assertEquals(3, summary.enabledReminderCount)
        assertTrue(summary.reminderPermissionMismatch)
    }

    @Test
    fun summaryDoesNotWarnWhenNoReminderIsEnabled() {
        val summary = notificationPreferencesSummary(
            preferences = NotificationPreferences(),
            readOnly = false,
            listenerAuthorized = false,
            systemNotificationsAllowed = false,
        )

        assertEquals(NotificationSettingState.Disabled, summary.autoDraftState)
        assertEquals(0, summary.enabledReminderCount)
        assertFalse(summary.reminderPermissionMismatch)
    }
}

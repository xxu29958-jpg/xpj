package com.ticketbox.ui.screens.settings

import com.ticketbox.domain.model.NotificationPreferences

internal enum class NotificationSettingState {
    Enabled,
    Disabled,
    ReadOnly,
    AwaitingAuthorization,
}
internal data class NotificationPreferencesSummary(
    val autoDraftState: NotificationSettingState,
    val enabledReminderCount: Int,
    val reminderPermissionMismatch: Boolean,
)

internal fun notificationPreferencesSummary(
    preferences: NotificationPreferences,
    readOnly: Boolean,
    listenerAuthorized: Boolean,
    systemNotificationsAllowed: Boolean,
): NotificationPreferencesSummary {
    val enabledReminderCount = listOf(
        preferences.pendingDraftReminders,
        preferences.largeAmountAlerts,
        preferences.recurringReminders,
        preferences.budgetOverspendAlerts,
        preferences.backupStaleAlerts,
    ).count { it }
    return NotificationPreferencesSummary(
        autoDraftState = when {
            readOnly -> NotificationSettingState.ReadOnly
            preferences.autoCaptureEnabled && !listenerAuthorized -> NotificationSettingState.AwaitingAuthorization
            preferences.autoCaptureEnabled -> NotificationSettingState.Enabled
            else -> NotificationSettingState.Disabled
        },
        enabledReminderCount = enabledReminderCount,
        reminderPermissionMismatch = enabledReminderCount > 0 && !systemNotificationsAllowed,
    )
}

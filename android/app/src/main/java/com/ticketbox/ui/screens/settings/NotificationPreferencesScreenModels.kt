package com.ticketbox.ui.screens.settings

import com.ticketbox.domain.model.NotificationPreferences

internal enum class NotificationSettingState {
    Enabled,
    Disabled,
    ReadOnly,
}

internal enum class NotificationPermissionState {
    Granted,
    Missing,
}

internal data class NotificationPreferencesSummary(
    val autoDraftState: NotificationSettingState,
    val listenerState: NotificationPermissionState,
    val systemNotificationState: NotificationPermissionState,
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
            preferences.autoCaptureEnabled -> NotificationSettingState.Enabled
            else -> NotificationSettingState.Disabled
        },
        listenerState = listenerAuthorized.toPermissionState(),
        systemNotificationState = systemNotificationsAllowed.toPermissionState(),
        enabledReminderCount = enabledReminderCount,
        reminderPermissionMismatch = enabledReminderCount > 0 && !systemNotificationsAllowed,
    )
}

private fun Boolean.toPermissionState(): NotificationPermissionState =
    if (this) NotificationPermissionState.Granted else NotificationPermissionState.Missing

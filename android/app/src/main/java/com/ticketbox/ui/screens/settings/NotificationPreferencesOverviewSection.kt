package com.ticketbox.ui.screens.settings

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.design.AppSpacing

@Composable
internal fun NotificationPreferencesOverviewSection(summary: NotificationPreferencesSummary) {
    SettingsSection(
        title = stringResource(R.string.notification_preferences_section_overview),
        icon = Icons.Filled.Notifications,
    ) {
        SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            SettingsMetricGrid(
                metrics = listOf(
                    SettingsMetricData(
                        label = stringResource(R.string.notification_preferences_overview_auto_draft_label),
                        value = stringResource(autoDraftValueRes(summary.autoDraftState)),
                        caption = stringResource(autoDraftCaptionRes(summary.autoDraftState)),
                    ),
                    SettingsMetricData(
                        label = stringResource(R.string.notification_preferences_overview_listener_label),
                        value = stringResource(permissionLabelRes(summary.listenerState)),
                        caption = stringResource(R.string.notification_preferences_overview_listener_caption),
                    ),
                    SettingsMetricData(
                        label = stringResource(R.string.notification_preferences_overview_reminders_label),
                        value = stringResource(
                            R.string.notification_preferences_overview_reminders_value,
                            summary.enabledReminderCount,
                        ),
                        caption = stringResource(R.string.notification_preferences_overview_reminders_caption),
                    ),
                    SettingsMetricData(
                        label = stringResource(R.string.notification_preferences_overview_system_label),
                        value = stringResource(permissionLabelRes(summary.systemNotificationState)),
                        caption = stringResource(R.string.notification_preferences_overview_system_caption),
                    ),
                ),
            )
            Text(
                text = stringResource(R.string.notification_preferences_overview_boundary),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@StringRes
private fun autoDraftValueRes(state: NotificationSettingState): Int = when (state) {
    NotificationSettingState.Enabled -> R.string.notification_preferences_overview_state_on
    NotificationSettingState.Disabled -> R.string.notification_preferences_overview_state_off
    NotificationSettingState.ReadOnly -> R.string.notification_preferences_overview_state_readonly
}

@StringRes
private fun autoDraftCaptionRes(state: NotificationSettingState): Int = when (state) {
    NotificationSettingState.Enabled -> R.string.notification_preferences_overview_auto_draft_caption_on
    NotificationSettingState.Disabled -> R.string.notification_preferences_overview_auto_draft_caption_off
    NotificationSettingState.ReadOnly -> R.string.notification_preferences_overview_auto_draft_caption_readonly
}

@StringRes
private fun permissionLabelRes(state: NotificationPermissionState): Int = when (state) {
    NotificationPermissionState.Granted -> R.string.notification_preferences_overview_permission_granted
    NotificationPermissionState.Missing -> R.string.notification_preferences_overview_permission_missing
}

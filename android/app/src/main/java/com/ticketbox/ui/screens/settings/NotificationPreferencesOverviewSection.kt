package com.ticketbox.ui.screens.settings

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
internal fun NotificationPreferencesOverviewSection(summary: NotificationPreferencesSummary) {
    SettingsSection(
        title = stringResource(R.string.notification_preferences_section_overview),
        icon = Icons.Filled.Notifications,
    ) {
        SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            NotificationOverviewRow(
                first = NotificationOverviewMetricData(
                    label = stringResource(R.string.notification_preferences_overview_auto_draft_label),
                    value = stringResource(autoDraftValueRes(summary.autoDraftState)),
                    caption = stringResource(autoDraftCaptionRes(summary.autoDraftState)),
                ),
                second = NotificationOverviewMetricData(
                    label = stringResource(R.string.notification_preferences_overview_listener_label),
                    value = stringResource(permissionLabelRes(summary.listenerState)),
                    caption = stringResource(R.string.notification_preferences_overview_listener_caption),
                ),
            )
            NotificationOverviewRow(
                first = NotificationOverviewMetricData(
                    label = stringResource(R.string.notification_preferences_overview_reminders_label),
                    value = stringResource(
                        R.string.notification_preferences_overview_reminders_value,
                        summary.enabledReminderCount,
                    ),
                    caption = stringResource(R.string.notification_preferences_overview_reminders_caption),
                ),
                second = NotificationOverviewMetricData(
                    label = stringResource(R.string.notification_preferences_overview_system_label),
                    value = stringResource(permissionLabelRes(summary.systemNotificationState)),
                    caption = stringResource(R.string.notification_preferences_overview_system_caption),
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

@Composable
private fun NotificationOverviewRow(
    first: NotificationOverviewMetricData,
    second: NotificationOverviewMetricData,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        NotificationOverviewMetric(data = first, modifier = Modifier.weight(1f))
        NotificationOverviewMetric(data = second, modifier = Modifier.weight(1f))
    }
}

@Composable
private fun NotificationOverviewMetric(
    data: NotificationOverviewMetricData,
    modifier: Modifier = Modifier,
) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        Text(
            text = data.label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 1,
        )
        Text(
            text = data.value,
            style = MaterialTheme.typography.titleMedium,
            fontWeight = AppTextHierarchy.heading.weight,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = data.caption,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelSmall,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

private data class NotificationOverviewMetricData(
    val label: String,
    val value: String,
    val caption: String,
)

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

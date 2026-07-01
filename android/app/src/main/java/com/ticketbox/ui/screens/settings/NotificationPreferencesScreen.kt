package com.ticketbox.ui.screens.settings

import android.Manifest
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.core.app.NotificationManagerCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import com.ticketbox.R
import com.ticketbox.domain.model.NotificationPreferences
import com.ticketbox.notification.NotificationListenerStatus
import com.ticketbox.ui.components.AppSwitch
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

@Composable
fun NotificationPreferencesScreen(
    preferences: NotificationPreferences,
    readOnly: Boolean,
    // Page-header status feedback is supplied by the settings host.
    status: (@Composable () -> Unit)? = null,
    onBack: () -> Unit,
    onSave: (NotificationPreferences) -> Unit,
) {
    val systemState = rememberNotificationSystemState()
    val summary = remember(
        preferences,
        readOnly,
        systemState.listenerAuthorized,
        systemState.systemNotificationsAllowed,
    ) {
        notificationPreferencesSummary(
            preferences = preferences,
            readOnly = readOnly,
            listenerAuthorized = systemState.listenerAuthorized,
            systemNotificationsAllowed = systemState.systemNotificationsAllowed,
        )
    }

    SettingsPageFrame(
        title = stringResource(R.string.notification_preferences_page_title),
        subtitle = stringResource(R.string.notification_preferences_page_subtitle),
        onBack = onBack,
        status = status,
    ) {
        NotificationPreferencesOverviewSection(summary)
        NotificationAutoDraftSection(
            preferences = preferences,
            readOnly = readOnly,
            listenerAuthorized = systemState.listenerAuthorized,
            onOpenAuthorization = systemState.openListenerSettings,
            onUpdate = onSave,
        )
        NotificationReminderSection(
            preferences = preferences,
            summary = summary,
            systemNotificationsAllowed = systemState.systemNotificationsAllowed,
            onRequestPermission = systemState.requestPostNotifications,
            onUpdate = onSave,
        )
        NotificationPrivacySection()
    }
}

@Composable
private fun rememberNotificationSystemState(): NotificationSystemState {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    var listenerAuthorized by remember {
        mutableStateOf(NotificationListenerStatus.isEnabled(context))
    }
    var systemNotificationsAllowed by remember {
        mutableStateOf(NotificationManagerCompat.from(context).areNotificationsEnabled())
    }
    fun refreshSystemState() {
        listenerAuthorized = NotificationListenerStatus.isEnabled(context)
        systemNotificationsAllowed = NotificationManagerCompat.from(context).areNotificationsEnabled()
    }
    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) {
        refreshSystemState()
    }
    DisposableEffect(context, lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_RESUME) {
                refreshSystemState()
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
    return NotificationSystemState(
        listenerAuthorized = listenerAuthorized,
        systemNotificationsAllowed = systemNotificationsAllowed,
        requestPostNotifications = { permissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS) },
        openListenerSettings = { context.startActivity(NotificationListenerStatus.settingsIntent()) },
    )
}

private data class NotificationSystemState(
    val listenerAuthorized: Boolean,
    val systemNotificationsAllowed: Boolean,
    val requestPostNotifications: () -> Unit,
    val openListenerSettings: () -> Unit,
)

@Composable
private fun NotificationAutoDraftSection(
    preferences: NotificationPreferences,
    readOnly: Boolean,
    listenerAuthorized: Boolean,
    onOpenAuthorization: () -> Unit,
    onUpdate: (NotificationPreferences) -> Unit,
) {
    SettingsSection(
        title = stringResource(R.string.notification_preferences_section_auto_draft),
        icon = Icons.Filled.Notifications,
    ) {
        SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            NotificationSwitchLine(
                title = stringResource(R.string.notification_preferences_capture_title),
                subtitle = when {
                    readOnly -> stringResource(R.string.notification_preferences_capture_subtitle_readonly)
                    listenerAuthorized -> stringResource(R.string.notification_preferences_capture_subtitle_authorized)
                    else -> stringResource(R.string.notification_preferences_capture_subtitle_default)
                },
                checked = preferences.autoCaptureEnabled && !readOnly,
                enabled = !readOnly,
                onCheckedChange = { onUpdate(preferences.copy(autoCaptureEnabled = it)) },
            )
            Button(
                onClick = onOpenAuthorization,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    if (listenerAuthorized) {
                        stringResource(R.string.notification_preferences_grant_view)
                    } else {
                        stringResource(R.string.notification_preferences_grant_open)
                    },
                )
            }
            Text(
                text = when {
                    readOnly -> stringResource(R.string.notification_preferences_capture_note_readonly)
                    preferences.autoCaptureEnabled -> stringResource(R.string.notification_preferences_capture_note_enabled)
                    else -> stringResource(R.string.notification_preferences_capture_note_disabled)
                },
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun NotificationReminderSection(
    preferences: NotificationPreferences,
    summary: NotificationPreferencesSummary,
    systemNotificationsAllowed: Boolean,
    onRequestPermission: () -> Unit,
    onUpdate: (NotificationPreferences) -> Unit,
) {
    SettingsSection(
        title = stringResource(R.string.notification_preferences_section_reminders),
        icon = Icons.Filled.Notifications,
    ) {
        SettingsOpenPanel(
            verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        ) {
            val rows = reminderRows(preferences)
            rows.forEachIndexed { index, row ->
                NotificationReminderRow(
                    row = row,
                    showDivider = index != rows.lastIndex,
                    systemNotificationsAllowed = systemNotificationsAllowed,
                    onRequestPermission = onRequestPermission,
                    onUpdate = onUpdate,
                )
            }
            ReminderPermissionHint(show = summary.reminderPermissionMismatch)
        }
    }
}

@Composable
private fun NotificationReminderRow(
    row: ReminderToggleRow,
    showDivider: Boolean,
    systemNotificationsAllowed: Boolean,
    onRequestPermission: () -> Unit,
    onUpdate: (NotificationPreferences) -> Unit,
) {
    NotificationSwitchLine(
        title = stringResource(row.titleRes),
        subtitle = stringResource(row.subtitleRes),
        checked = row.checked,
        onCheckedChange = { turnedOn ->
            if (turnedOn && shouldRequestPostNotifications(systemNotificationsAllowed)) {
                onRequestPermission()
            }
            onUpdate(row.updated(turnedOn))
        },
    )
    if (showDivider) {
        HorizontalDivider(
            color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium),
        )
    }
}

@Composable
private fun ReminderPermissionHint(show: Boolean) {
    if (!show) return
    Text(
        text = stringResource(R.string.notification_preferences_system_permission_hint),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodySmall,
    )
}

@Composable
private fun NotificationPrivacySection() {
    SettingsSection(
        title = stringResource(R.string.notification_preferences_section_privacy),
        icon = Icons.Filled.Notifications,
    ) {
        SettingsOpenPanel(
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Text(
                text = stringResource(R.string.notification_preferences_privacy_title),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = stringResource(R.string.notification_preferences_privacy_body),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
    }
}

@Composable
private fun NotificationSwitchLine(
    title: String,
    subtitle: String,
    checked: Boolean,
    enabled: Boolean = true,
    onCheckedChange: (Boolean) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier
                .weight(1f)
                .padding(end = AppSpacing.compactGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = AppTextHierarchy.body.weight,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
            Text(
                text = subtitle,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis,
            )
        }
        AppSwitch(
            checked = checked,
            enabled = enabled,
            onCheckedChange = onCheckedChange,
        )
    }
}

private data class ReminderToggleRow(
    @param:StringRes val titleRes: Int,
    @param:StringRes val subtitleRes: Int,
    val checked: Boolean,
    val updated: (Boolean) -> NotificationPreferences,
)

private fun reminderRows(preferences: NotificationPreferences): List<ReminderToggleRow> = listOf(
    ReminderToggleRow(
        titleRes = R.string.notification_preferences_reminder_pending_title,
        subtitleRes = R.string.notification_preferences_reminder_pending_subtitle,
        checked = preferences.pendingDraftReminders,
        updated = { preferences.copy(pendingDraftReminders = it) },
    ),
    ReminderToggleRow(
        titleRes = R.string.notification_preferences_reminder_large_amount_title,
        subtitleRes = R.string.notification_preferences_reminder_large_amount_subtitle,
        checked = preferences.largeAmountAlerts,
        updated = { preferences.copy(largeAmountAlerts = it) },
    ),
    ReminderToggleRow(
        titleRes = R.string.notification_preferences_reminder_recurring_title,
        subtitleRes = R.string.notification_preferences_reminder_recurring_subtitle,
        checked = preferences.recurringReminders,
        updated = { preferences.copy(recurringReminders = it) },
    ),
    ReminderToggleRow(
        titleRes = R.string.notification_preferences_reminder_budget_title,
        subtitleRes = R.string.notification_preferences_reminder_budget_subtitle,
        checked = preferences.budgetOverspendAlerts,
        updated = { preferences.copy(budgetOverspendAlerts = it) },
    ),
    ReminderToggleRow(
        titleRes = R.string.notification_preferences_reminder_backup_title,
        subtitleRes = R.string.notification_preferences_reminder_backup_subtitle,
        checked = preferences.backupStaleAlerts,
        updated = { preferences.copy(backupStaleAlerts = it) },
    ),
)

private fun shouldRequestPostNotifications(systemNotificationsAllowed: Boolean): Boolean =
    Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && !systemNotificationsAllowed

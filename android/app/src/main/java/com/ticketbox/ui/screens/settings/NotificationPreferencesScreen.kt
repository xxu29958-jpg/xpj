package com.ticketbox.ui.screens.settings

import android.Manifest
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material3.Button
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.core.app.NotificationManagerCompat
import com.ticketbox.R
import com.ticketbox.domain.model.NotificationPreferences
import com.ticketbox.notification.NotificationListenerStatus
import com.ticketbox.ui.components.AppSwitch
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.design.AppSpacing

@Composable
fun NotificationPreferencesScreen(
    preferences: NotificationPreferences,
    readOnly: Boolean,
    onBack: () -> Unit,
    onSave: (NotificationPreferences) -> Unit,
) {
    fun update(updated: NotificationPreferences) {
        onSave(updated)
    }
    val context = LocalContext.current
    val listenerAuthorized = NotificationListenerStatus.isEnabled(context)

    SettingsPageFrame(
        title = stringResource(R.string.notification_preferences_page_title),
        subtitle = stringResource(R.string.notification_preferences_page_subtitle),
        onBack = onBack,
    ) {
        SettingsSection(
            title = stringResource(R.string.notification_preferences_section_auto_draft),
            icon = Icons.Filled.Notifications,
        ) {
            AppGlassCard(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(AppSpacing.cardPaddingTight),
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
                ) {
                    NotificationSwitchLine(
                        title = stringResource(R.string.notification_preferences_capture_title),
                        subtitle = if (readOnly) {
                            stringResource(R.string.notification_preferences_capture_subtitle_readonly)
                        } else if (listenerAuthorized) {
                            stringResource(R.string.notification_preferences_capture_subtitle_authorized)
                        } else {
                            stringResource(R.string.notification_preferences_capture_subtitle_default)
                        },
                        checked = preferences.autoCaptureEnabled && !readOnly,
                        enabled = !readOnly,
                        onCheckedChange = {
                            update(preferences.copy(autoCaptureEnabled = it))
                        },
                    )
                    Button(
                        onClick = {
                            context.startActivity(NotificationListenerStatus.settingsIntent())
                        },
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
                        text = if (readOnly) {
                            stringResource(R.string.notification_preferences_capture_note_readonly)
                        } else if (preferences.autoCaptureEnabled) {
                            stringResource(R.string.notification_preferences_capture_note_enabled)
                        } else {
                            stringResource(R.string.notification_preferences_capture_note_disabled)
                        },
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        }
        SettingsSection(
            title = stringResource(R.string.notification_preferences_section_reminders),
            icon = Icons.Filled.Notifications,
        ) {
            ReminderSwitchesCard(
                preferences = preferences,
                onUpdate = { update(it) },
            )
        }
        SettingsSection(
            title = stringResource(R.string.notification_preferences_section_privacy),
            icon = Icons.Filled.Notifications,
        ) {
            AppGlassCard(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(AppSpacing.cardPaddingTight),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(
                        text = stringResource(R.string.notification_preferences_privacy_title),
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        text = stringResource(R.string.notification_preferences_privacy_body),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }
        }
    }
}

/**
 * 提醒开关卡片（通知闭环 PR-1）：任一提醒开关 off→on 且系统未授权时请求
 * POST_NOTIFICATIONS（API 33+）；拒绝后开关照存，由底部提示行说明提醒不会展示
 * （镜像上方 listenerAuthorized 状态行模式）。
 */
@Composable
private fun ReminderSwitchesCard(
    preferences: NotificationPreferences,
    onUpdate: (NotificationPreferences) -> Unit,
) {
    val context = LocalContext.current
    var systemNotificationsAllowed by remember {
        mutableStateOf(NotificationManagerCompat.from(context).areNotificationsEnabled())
    }
    val permissionLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.RequestPermission(),
    ) { _ ->
        systemNotificationsAllowed = NotificationManagerCompat.from(context).areNotificationsEnabled()
    }
    fun toggleReminder(turnedOn: Boolean, updated: NotificationPreferences) {
        if (turnedOn && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && !systemNotificationsAllowed) {
            permissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        }
        onUpdate(updated)
    }
    AppGlassCard(containerAlpha = 0.96f) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingTight),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
        ) {
            NotificationSwitchLine(
                title = stringResource(R.string.notification_preferences_reminder_pending_title),
                subtitle = stringResource(R.string.notification_preferences_reminder_pending_subtitle),
                checked = preferences.pendingDraftReminders,
                onCheckedChange = { toggleReminder(it, preferences.copy(pendingDraftReminders = it)) },
            )
            NotificationSwitchLine(
                title = stringResource(R.string.notification_preferences_reminder_large_amount_title),
                subtitle = stringResource(R.string.notification_preferences_reminder_large_amount_subtitle),
                checked = preferences.largeAmountAlerts,
                onCheckedChange = { toggleReminder(it, preferences.copy(largeAmountAlerts = it)) },
            )
            NotificationSwitchLine(
                title = stringResource(R.string.notification_preferences_reminder_recurring_title),
                subtitle = stringResource(R.string.notification_preferences_reminder_recurring_subtitle),
                checked = preferences.recurringReminders,
                onCheckedChange = { toggleReminder(it, preferences.copy(recurringReminders = it)) },
            )
            ReminderPermissionHint(
                preferences = preferences,
                systemNotificationsAllowed = systemNotificationsAllowed,
            )
        }
    }
}

/** 任一提醒开关开着但系统通知不可用时的提示行。 */
@Composable
private fun ReminderPermissionHint(
    preferences: NotificationPreferences,
    systemNotificationsAllowed: Boolean,
) {
    val anyReminderEnabled = preferences.pendingDraftReminders ||
        preferences.largeAmountAlerts ||
        preferences.recurringReminders
    if (!anyReminderEnabled || systemNotificationsAllowed) return
    Text(
        text = stringResource(R.string.notification_preferences_system_permission_hint),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodySmall,
    )
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
            verticalArrangement = Arrangement.spacedBy(3.dp),
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.bodyLarge,
                fontWeight = FontWeight.SemiBold,
            )
            Text(
                text = subtitle,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        AppSwitch(
            checked = checked,
            enabled = enabled,
            onCheckedChange = onCheckedChange,
        )
    }
}

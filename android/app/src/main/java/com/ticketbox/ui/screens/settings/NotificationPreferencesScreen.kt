package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Notifications
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.NotificationPreferences
import com.ticketbox.ui.components.SoftPanel

@Composable
fun NotificationPreferencesScreen(
    preferences: NotificationPreferences,
    onBack: () -> Unit,
    onSave: (NotificationPreferences) -> Unit,
) {
    fun update(updated: NotificationPreferences) {
        onSave(updated)
    }

    SettingsPageFrame(
        title = "通知与提醒",
        subtitle = "通知只生成待确认草稿或提醒，不会自动入账。",
        onBack = onBack,
    ) {
        SettingsSection(title = "提醒开关", icon = Icons.Filled.Notifications) {
            SoftPanel(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(14.dp),
                ) {
                    NotificationSwitchLine(
                        title = "待确认提醒",
                        subtitle = "有新的待确认草稿时提醒你回来核对。",
                        checked = preferences.pendingDraftReminders,
                        onCheckedChange = {
                            update(preferences.copy(pendingDraftReminders = it))
                        },
                    )
                    NotificationSwitchLine(
                        title = "大额提醒",
                        subtitle = "结构化通知金额偏高时提醒，仍需手动确认。",
                        checked = preferences.largeAmountAlerts,
                        onCheckedChange = {
                            update(preferences.copy(largeAmountAlerts = it))
                        },
                    )
                    NotificationSwitchLine(
                        title = "固定支出提醒",
                        subtitle = "固定支出临近或金额异常时提醒。",
                        checked = preferences.recurringReminders,
                        onCheckedChange = {
                            update(preferences.copy(recurringReminders = it))
                        },
                    )
                }
            }
        }
        SettingsSection(title = "隐私边界", icon = Icons.Filled.Notifications) {
            SoftPanel(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(14.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(
                        text = "通知原文不会上传到小票夹服务。",
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        text = "后续开启通知监听前，会先要求你在系统设置中显式授权，并且可以在这里一键关闭提醒。",
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodyMedium,
                    )
                }
            }
        }
    }
}

@Composable
private fun NotificationSwitchLine(
    title: String,
    subtitle: String,
    checked: Boolean,
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
                .padding(end = 12.dp),
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
        Switch(checked = checked, onCheckedChange = onCheckedChange)
    }
}

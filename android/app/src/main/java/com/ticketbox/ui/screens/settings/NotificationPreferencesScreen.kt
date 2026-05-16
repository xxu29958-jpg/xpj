package com.ticketbox.ui.screens.settings

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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
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
        title = "通知与提醒",
        subtitle = "通知只生成待确认草稿或提醒，不会自动入账。",
        onBack = onBack,
    ) {
        SettingsSection(title = "通知自动草稿", icon = Icons.Filled.Notifications) {
            AppGlassCard(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(AppSpacing.cardPaddingTight),
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
                ) {
                    NotificationSwitchLine(
                        title = "本机解析支付通知",
                        subtitle = if (readOnly) {
                            "当前角色为只读，不能生成自动草稿。"
                        } else if (listenerAuthorized) {
                            "系统授权已开启；只上传来源、金额、商家、分类和时间。"
                        } else {
                            "需要先在系统设置里显式授权；关闭后不会读取通知。"
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
                        Text(if (listenerAuthorized) "查看系统授权" else "打开系统授权")
                    }
                    Text(
                        text = if (readOnly) {
                            "当前角色为只读，通知监听服务不会生成草稿。"
                        } else if (preferences.autoCaptureEnabled) {
                            "自动草稿仍需在待确认页手动确认，绝不会自动入账。"
                        } else {
                            "当前已关闭自动草稿，通知监听服务不会上传任何内容。"
                        },
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        }
        SettingsSection(title = "提醒开关", icon = Icons.Filled.Notifications) {
            AppGlassCard(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(AppSpacing.cardPaddingTight),
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
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
            AppGlassCard(containerAlpha = 0.96f) {
                Column(
                    modifier = Modifier.padding(AppSpacing.cardPaddingTight),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    Text(
                        text = "通知原文不会上传到小票夹服务。",
                        style = MaterialTheme.typography.titleSmall,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(
                        text = "支付通知只在本机解析，上传字段限定为来源、金额、商家、分类和时间。系统授权和 App 开关任一关闭，都会停止自动草稿。",
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

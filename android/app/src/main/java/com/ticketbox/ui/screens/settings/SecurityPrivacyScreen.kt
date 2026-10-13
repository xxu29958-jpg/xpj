package com.ticketbox.ui.screens.settings

import androidx.annotation.StringRes
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.Devices
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Key
import androidx.compose.material.icons.outlined.Security
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.unit.dp
import com.ticketbox.BuildConfig
import com.ticketbox.R
import com.ticketbox.ui.components.SettingsEntryIcon
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.SettingsColors

internal enum class SecurityPrivacyInfoKind {
    LocalUnlock,
    SessionCredential,
    BackgroundPrivacy,
}

internal enum class SecurityDangerActionKind {
    ClearOfflineCopy,
    LeaveLedger,
}

internal data class SecurityPrivacyInfoRowModel(
    val kind: SecurityPrivacyInfoKind,
    @param:StringRes val titleRes: Int,
    @param:StringRes val bodyRes: Int,
)

internal data class SecurityDangerActionModel(
    val kind: SecurityDangerActionKind,
    @param:StringRes val titleRes: Int,
    @param:StringRes val bodyRes: Int,
    @param:StringRes val buttonRes: Int,
    @param:StringRes val contentDescriptionRes: Int,
    @param:StringRes val dialogTitleRes: Int,
    @param:StringRes val dialogTextRes: Int,
    @param:StringRes val dialogConfirmRes: Int,
    val enabled: Boolean,
)

internal fun securityPrivacyInfoRows(requireLocalUnlock: Boolean): List<SecurityPrivacyInfoRowModel> = listOf(
    SecurityPrivacyInfoRowModel(
        kind = SecurityPrivacyInfoKind.LocalUnlock,
        titleRes = if (requireLocalUnlock) {
            R.string.settings_security_local_unlock_label_locked
        } else {
            R.string.settings_security_local_unlock_label_unlocked
        },
        bodyRes = if (requireLocalUnlock) {
            R.string.settings_security_local_unlock_body_locked
        } else {
            R.string.settings_security_local_unlock_body_unlocked
        },
    ),
    SecurityPrivacyInfoRowModel(
        kind = SecurityPrivacyInfoKind.SessionCredential,
        titleRes = R.string.settings_security_session_label,
        bodyRes = R.string.settings_security_session_body,
    ),
    SecurityPrivacyInfoRowModel(
        kind = SecurityPrivacyInfoKind.BackgroundPrivacy,
        titleRes = R.string.settings_security_background_label,
        bodyRes = R.string.settings_security_background_body,
    ),
)

internal fun securityDangerActions(actionsEnabled: Boolean = true): List<SecurityDangerActionModel> = listOf(
    SecurityDangerActionModel(
        kind = SecurityDangerActionKind.ClearOfflineCopy,
        titleRes = R.string.settings_security_danger_clear_copy_label,
        bodyRes = R.string.settings_security_danger_clear_copy_body,
        buttonRes = R.string.settings_security_button_clear_data,
        contentDescriptionRes = R.string.settings_security_clear_data_icon_desc,
        dialogTitleRes = R.string.settings_security_clear_dialog_title,
        dialogTextRes = R.string.settings_security_clear_dialog_text,
        dialogConfirmRes = R.string.settings_security_clear_dialog_confirm,
        enabled = actionsEnabled,
    ),
    SecurityDangerActionModel(
        kind = SecurityDangerActionKind.LeaveLedger,
        titleRes = R.string.settings_security_danger_logout_label,
        bodyRes = R.string.settings_security_danger_logout_body,
        buttonRes = R.string.settings_security_button_logout,
        contentDescriptionRes = R.string.settings_security_logout_icon_desc,
        dialogTitleRes = R.string.settings_security_logout_dialog_title,
        dialogTextRes = R.string.settings_security_logout_dialog_text,
        dialogConfirmRes = R.string.settings_security_logout_dialog_confirm,
        enabled = actionsEnabled,
    ),
)

@Composable
fun SecurityPrivacyScreen(
    onBack: () -> Unit,
    onClearCache: () -> Unit,
    onBindingCleared: () -> Unit,
    busy: Boolean = false,
    // Page-header status feedback (this screen used to render none; the host
    // builds an AppStatusBanner from SettingsViewModel's message + tone.
    status: (@Composable () -> Unit)? = null,
) {
    var pendingActionKind by remember { mutableStateOf<SecurityDangerActionKind?>(null) }
    val actionsEnabled = !busy
    val actions = remember(actionsEnabled) { securityDangerActions(actionsEnabled) }
    val pendingAction = pendingActionKind?.let { kind -> actions.firstOrNull { it.kind == kind } }

    pendingAction?.let { action ->
        SecurityConfirmDialog(
            action = action,
            onDismiss = { pendingActionKind = null },
            onClearCache = onClearCache,
            onBindingCleared = onBindingCleared,
        )
    }

    SettingsPageFrame(
        title = stringResource(R.string.settings_security_page_title),
        subtitle = stringResource(R.string.settings_security_page_subtitle),
        onBack = onBack,
        status = status,
    ) {
        SecurityInfoSection(requireLocalUnlock = BuildConfig.REQUIRE_LOCAL_UNLOCK)
        SecurityDangerSection(
            actions = actions,
            onActionClick = { action -> pendingActionKind = action },
        )
        SettingsSection(
            title = stringResource(R.string.settings_security_confirmation_title),
        ) {
            Text(stringResource(R.string.settings_security_confirmation_body),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun SecurityConfirmDialog(
    action: SecurityDangerActionModel,
    onDismiss: () -> Unit,
    onClearCache: () -> Unit,
    onBindingCleared: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(action.dialogTitleRes)) },
        text = { Text(stringResource(action.dialogTextRes)) },
        confirmButton = {
            TextButton(
                enabled = action.enabled,
                colors = ButtonDefaults.textButtonColors(contentColor = MaterialTheme.colorScheme.error),
                onClick = {
                    onDismiss()
                    when (action.kind) {
                        SecurityDangerActionKind.ClearOfflineCopy -> onClearCache()
                        SecurityDangerActionKind.LeaveLedger -> onBindingCleared()
                    }
                },
            ) {
                Text(
                    text = stringResource(action.dialogConfirmRes),
                )
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(stringResource(R.string.common_cancel))
            }
        },
    )
}

@Composable
private fun SecurityInfoSection(requireLocalUnlock: Boolean) {
    SettingsSection(
        title = stringResource(R.string.settings_security_section_protection),
    ) {
        val rows = remember(requireLocalUnlock) { securityPrivacyInfoRows(requireLocalUnlock) }
        SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(0.dp)) {
            rows.forEachIndexed { index, row ->
                if (index > 0) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
                }
                SecurityInfoRow(row)
            }
        }
    }
}

@Composable
private fun SecurityInfoRow(row: SecurityPrivacyInfoRowModel) {
    val icon = when (row.kind) {
        SecurityPrivacyInfoKind.LocalUnlock -> Icons.Outlined.Security
        SecurityPrivacyInfoKind.SessionCredential -> Icons.Outlined.Key
        SecurityPrivacyInfoKind.BackgroundPrivacy -> Icons.Outlined.Image
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 72.dp)
            .padding(vertical = AppSpacing.contentGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.Top,
    ) {
        SettingsEntryIcon(icon = icon, shape = RoundedCornerShape(14.dp),
            background = if (row.kind == SecurityPrivacyInfoKind.SessionCredential) {
                SettingsColors.sessionCredential
            } else SettingsColors.generalEntry)
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Text(
                text = stringResource(row.titleRes),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = stringResource(row.bodyRes),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun SecurityDangerSection(
    actions: List<SecurityDangerActionModel>,
    onActionClick: (SecurityDangerActionKind) -> Unit,
) {
    SettingsSection(
        title = stringResource(R.string.settings_security_section_danger),
    ) {
        SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(0.dp)) {
            actions.forEachIndexed { index, action ->
                if (index > 0) {
                    HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium))
                }
                SecurityDangerRow(
                    action = action,
                    onClick = { onActionClick(action.kind) },
                )
            }
        }
    }
}

@Composable
private fun SecurityDangerRow(
    action: SecurityDangerActionModel,
    onClick: () -> Unit,
) {
    val icon = when (action.kind) {
        SecurityDangerActionKind.ClearOfflineCopy -> Icons.Outlined.Devices
        SecurityDangerActionKind.LeaveLedger -> Icons.AutoMirrored.Filled.Logout
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(min = 72.dp)
            .clip(RoundedCornerShape(AppRadius.small))
            .clickable(enabled = action.enabled, role = Role.Button, onClick = onClick)
            .padding(vertical = AppSpacing.contentGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.Top,
    ) {
        SettingsEntryIcon(icon = icon, shape = RoundedCornerShape(14.dp),
            background = when (action.kind) {
                SecurityDangerActionKind.ClearOfflineCopy -> SettingsColors.offlineCopy
                SecurityDangerActionKind.LeaveLedger -> SettingsColors.sessionExit
            })
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            SecurityDangerTitleRow(action = action)
            Text(
                text = stringResource(action.bodyRes),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun SecurityDangerTitleRow(action: SecurityDangerActionModel) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = stringResource(action.titleRes),
            style = MaterialTheme.typography.titleMedium,
            fontWeight = AppTextHierarchy.heading.weight,
            modifier = Modifier.weight(1f),
        )
        SecurityDangerInlineAction(action = action)
    }
}

@Composable
private fun SecurityDangerInlineAction(action: SecurityDangerActionModel) {
    val icon = when (action.kind) {
        SecurityDangerActionKind.ClearOfflineCopy -> Icons.Outlined.DeleteOutline
        SecurityDangerActionKind.LeaveLedger -> Icons.AutoMirrored.Filled.Logout
    }
    val actionColor = if (action.enabled) {
        MaterialTheme.colorScheme.error
    } else {
        MaterialTheme.colorScheme.onSurfaceVariant
    }
    Row(
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = stringResource(action.contentDescriptionRes),
            tint = actionColor,
            modifier = Modifier.size(17.dp),
        )
        Text(
            text = stringResource(action.buttonRes),
            color = actionColor,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = AppTextHierarchy.heading.weight,
        )
    }
}

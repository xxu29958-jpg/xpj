package com.ticketbox.ui.screens.settings

import androidx.annotation.StringRes
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Logout
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material.icons.filled.Devices
import androidx.compose.material.icons.filled.Image
import androidx.compose.material.icons.filled.Key
import androidx.compose.material.icons.filled.Security
import androidx.compose.material3.AlertDialog
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
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.ticketbox.BuildConfig
import com.ticketbox.R
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

internal enum class SecurityPrivacyInfoKind {
    LocalUnlock,
    SessionCredential,
    BackgroundPrivacy,
}

internal enum class SecurityDangerActionKind {
    ClearOfflineCopy,
    LeaveLedger,
}

private enum class SecurityPendingDialog {
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

internal fun securityDangerActions(): List<SecurityDangerActionModel> = listOf(
    SecurityDangerActionModel(
        kind = SecurityDangerActionKind.ClearOfflineCopy,
        titleRes = R.string.settings_security_danger_clear_copy_label,
        bodyRes = R.string.settings_security_danger_clear_copy_body,
        buttonRes = R.string.settings_security_button_clear_data,
        contentDescriptionRes = R.string.settings_security_clear_data_icon_desc,
    ),
    SecurityDangerActionModel(
        kind = SecurityDangerActionKind.LeaveLedger,
        titleRes = R.string.settings_security_danger_logout_label,
        bodyRes = R.string.settings_security_danger_logout_body,
        buttonRes = R.string.settings_security_button_logout,
        contentDescriptionRes = R.string.settings_security_logout_icon_desc,
    ),
)

@Composable
fun SecurityPrivacyScreen(
    onBack: () -> Unit,
    onClearCache: () -> Unit,
    onBindingCleared: () -> Unit,
    // Page-header status feedback (this screen used to render none; the host
    // builds an AppStatusBanner from SettingsViewModel's message + tone.
    status: (@Composable () -> Unit)? = null,
) {
    var pendingDialog by remember { mutableStateOf<SecurityPendingDialog?>(null) }

    pendingDialog?.let { dialog ->
        SecurityConfirmDialog(
            dialog = dialog,
            onDismiss = { pendingDialog = null },
            onClearCache = onClearCache,
            onBindingCleared = onBindingCleared,
        )
    }

    SettingsPageFrame(
        title = stringResource(R.string.settings_security_page_title),
        subtitle = if (BuildConfig.REQUIRE_LOCAL_UNLOCK) {
            stringResource(R.string.settings_security_page_subtitle_locked)
        } else {
            stringResource(R.string.settings_security_page_subtitle_unlocked)
        },
        onBack = onBack,
        status = status,
    ) {
        SecurityInfoSection(requireLocalUnlock = BuildConfig.REQUIRE_LOCAL_UNLOCK)
        SecurityDangerSection(
            onActionClick = { action ->
                pendingDialog = when (action) {
                    SecurityDangerActionKind.ClearOfflineCopy -> SecurityPendingDialog.ClearOfflineCopy
                    SecurityDangerActionKind.LeaveLedger -> SecurityPendingDialog.LeaveLedger
                }
            },
        )
    }
}

@Composable
private fun SecurityConfirmDialog(
    dialog: SecurityPendingDialog,
    onDismiss: () -> Unit,
    onClearCache: () -> Unit,
    onBindingCleared: () -> Unit,
) {
    val copy = when (dialog) {
        SecurityPendingDialog.ClearOfflineCopy -> SecurityDialogCopy(
            titleRes = R.string.settings_security_clear_dialog_title,
            textRes = R.string.settings_security_clear_dialog_text,
            confirmRes = R.string.settings_security_clear_dialog_confirm,
        )
        SecurityPendingDialog.LeaveLedger -> SecurityDialogCopy(
            titleRes = R.string.settings_security_logout_dialog_title,
            textRes = R.string.settings_security_logout_dialog_text,
            confirmRes = R.string.settings_security_logout_dialog_confirm,
        )
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(copy.titleRes)) },
        text = { Text(stringResource(copy.textRes)) },
        confirmButton = {
            TextButton(
                onClick = {
                    onDismiss()
                    when (dialog) {
                        SecurityPendingDialog.ClearOfflineCopy -> onClearCache()
                        SecurityPendingDialog.LeaveLedger -> onBindingCleared()
                    }
                },
            ) {
                Text(
                    text = stringResource(copy.confirmRes),
                    color = MaterialTheme.colorScheme.error,
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
        icon = Icons.Filled.Security,
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
        SecurityPrivacyInfoKind.LocalUnlock -> Icons.Filled.Security
        SecurityPrivacyInfoKind.SessionCredential -> Icons.Filled.Key
        SecurityPrivacyInfoKind.BackgroundPrivacy -> Icons.Filled.Image
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.smallGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.Top,
    ) {
        SecurityIconBox(icon = icon)
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Text(
                text = stringResource(row.titleRes),
                style = MaterialTheme.typography.titleSmall,
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
private fun SecurityIconBox(icon: ImageVector) {
    Box(
        modifier = Modifier
            .size(AppSpacing.controlMinHeight)
            .clip(RoundedCornerShape(AppRadius.small))
            .background(MaterialTheme.colorScheme.primary.copy(alpha = AppAlpha.subtle)),
        contentAlignment = Alignment.Center,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(AppSpacing.cardPadding),
        )
    }
}

@Composable
private fun SecurityDangerSection(onActionClick: (SecurityDangerActionKind) -> Unit) {
    SettingsSection(
        title = stringResource(R.string.settings_security_section_danger),
        icon = Icons.Filled.DeleteOutline,
    ) {
        val actions = remember { securityDangerActions() }
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
        SecurityDangerActionKind.ClearOfflineCopy -> Icons.Filled.Devices
        SecurityDangerActionKind.LeaveLedger -> Icons.AutoMirrored.Filled.Logout
    }
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.smallGap),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        SecurityIconBox(icon = icon)
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Text(
                text = stringResource(action.titleRes),
                style = MaterialTheme.typography.titleSmall,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            Text(
                text = stringResource(action.bodyRes),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        SecurityDangerButton(action = action, onClick = onClick)
    }
}

@Composable
private fun SecurityDangerButton(action: SecurityDangerActionModel, onClick: () -> Unit) {
    val icon = when (action.kind) {
        SecurityDangerActionKind.ClearOfflineCopy -> Icons.Filled.DeleteOutline
        SecurityDangerActionKind.LeaveLedger -> Icons.AutoMirrored.Filled.Logout
    }
    AppOutlinedButton(
        danger = true,
        onClick = onClick,
    ) {
        Icon(
            imageVector = icon,
            contentDescription = stringResource(action.contentDescriptionRes),
            modifier = Modifier.size(18.dp),
        )
        Box(modifier = Modifier.width(AppSpacing.smallGap))
        Text(
            text = stringResource(action.buttonRes),
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            softWrap = false,
        )
    }
}

private data class SecurityDialogCopy(
    @param:StringRes val titleRes: Int,
    @param:StringRes val textRes: Int,
    @param:StringRes val confirmRes: Int,
)

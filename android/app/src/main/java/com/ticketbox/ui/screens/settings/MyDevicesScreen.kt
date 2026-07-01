package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Devices
import androidx.compose.material.icons.filled.GroupAdd
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.style.TextOverflow
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.AccountDevice
import com.ticketbox.domain.model.DevicePairingCode
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.MyDevicesUiState
import com.ticketbox.viewmodel.MyDevicesViewModel

/** Row management callbacks grouped so device rows stay small and stable. */
@Immutable
private class DeviceRowActions(
    val onRename: (AccountDevice) -> Unit,
    val onRevoke: (AccountDevice) -> Unit,
    val onDelete: (AccountDevice) -> Unit,
)

/** One nullable state enforces one device-management dialog at a time. */
private sealed interface DeviceDialog {
    val device: AccountDevice

    data class Rename(override val device: AccountDevice) : DeviceDialog
    data class Revoke(override val device: AccountDevice) : DeviceDialog
    data class Remove(override val device: AccountDevice) : DeviceDialog
}

@Composable
fun MyDevicesScreen(
    viewModel: MyDevicesViewModel,
    activeLedgerId: String?,
    onBack: () -> Unit,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val canManage = viewModel.deviceIsOwner()
    var dialog by remember { mutableStateOf<DeviceDialog?>(null) }
    val rowActions = remember {
        DeviceRowActions(
            onRename = { dialog = DeviceDialog.Rename(it) },
            onRevoke = { dialog = DeviceDialog.Revoke(it) },
            onDelete = { dialog = DeviceDialog.Remove(it) },
        )
    }

    LaunchedEffect(activeLedgerId) { viewModel.refresh(activeLedgerId) }
    DisposableEffect(viewModel) { onDispose { viewModel.dismissPairingCode() } }

    when (val open = dialog) {
        is DeviceDialog.Rename -> RenameDeviceDialog(
            device = open.device,
            onConfirm = { name -> viewModel.rename(open.device, name, activeLedgerId); dialog = null },
            onDismiss = { dialog = null },
        )
        is DeviceDialog.Revoke -> RevokeDeviceDialog(
            device = open.device,
            onConfirm = { viewModel.revoke(open.device, activeLedgerId); dialog = null },
            onDismiss = { dialog = null },
        )
        is DeviceDialog.Remove -> DeleteDeviceDialog(
            device = open.device,
            onConfirm = { viewModel.delete(open.device, activeLedgerId); dialog = null },
            onDismiss = { dialog = null },
        )
        null -> Unit
    }

    SettingsPageFrame(
        title = stringResource(R.string.my_devices_page_title),
        subtitle = if (canManage) {
            stringResource(R.string.my_devices_page_subtitle_manage)
        } else {
            stringResource(R.string.my_devices_page_subtitle_view)
        },
        onBack = onBack,
        status = { AppStatusBanner(message = state.message, tone = MessageTone.Neutral) },
    ) {
        DeviceListSection(
            state = state,
            canManage = canManage,
            onRefresh = { viewModel.refresh(activeLedgerId) },
            actions = rowActions,
        )
        if (canManage) {
            AddDeviceSection(
                creating = state.pairingCreating,
                createdCode = state.createdPairingCode,
                onCreate = { viewModel.createPairingCode(activeLedgerId) },
                onDismissResult = { viewModel.dismissPairingCode() },
            )
        }
    }
}

@Composable
private fun DeviceListSection(
    state: MyDevicesUiState,
    canManage: Boolean,
    onRefresh: () -> Unit,
    actions: DeviceRowActions,
) {
    SettingsSection(
        title = stringResource(R.string.my_devices_section_devices),
        icon = Icons.Filled.Devices,
    ) {
        SettingsOpenPanel(
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            if (state.devices.isEmpty() && state.loading) {
                SettingsInlineEmpty(
                    title = stringResource(R.string.my_devices_loading_title),
                    body = stringResource(R.string.my_devices_loading_body),
                )
            } else if (state.devices.isEmpty()) {
                Text(
                    text = stringResource(R.string.my_devices_empty),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            state.devices.forEachIndexed { index, device ->
                DeviceRow(
                    device = device,
                    canManage = canManage,
                    busy = state.busyDeviceId == device.publicId,
                    actions = actions,
                )
                if (index != state.devices.lastIndex) {
                    HorizontalDivider(
                        color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.medium),
                    )
                }
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
            ) {
                TextButton(
                    onClick = onRefresh,
                    enabled = !state.loading && state.busyDeviceId == null,
                ) {
                    Text(
                        if (state.loading) {
                            stringResource(R.string.my_devices_refresh_loading)
                        } else {
                            stringResource(R.string.my_devices_refresh)
                        },
                    )
                }
            }
        }
    }
}

@Composable
private fun DeviceRow(
    device: AccountDevice,
    canManage: Boolean,
    busy: Boolean,
    actions: DeviceRowActions,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = AppSpacing.miniGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        DeviceTitleRow(
            device = device,
            canManage = canManage,
            busy = busy,
            actions = actions,
        )
        DeviceActivityText(device = device)
    }
}

@Composable
private fun DeviceTitleRow(
    device: AccountDevice,
    canManage: Boolean,
    busy: Boolean,
    actions: DeviceRowActions,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = device.deviceName,
            style = MaterialTheme.typography.titleSmall,
            color = if (device.isRevoked) {
                MaterialTheme.colorScheme.onSurfaceVariant
            } else {
                MaterialTheme.colorScheme.onSurface
            },
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            modifier = Modifier.weight(1f),
        )
        if (device.isCurrent) {
            Spacer(Modifier.width(AppSpacing.miniGap + AppSpacing.tinyGap))
            Text(
                text = stringResource(R.string.my_devices_row_current_badge),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.primary,
            )
        }
        if (canManage) {
            DeviceActionsRow(device = device, busy = busy, actions = actions)
        }
    }
}

@Composable
private fun DeviceActivityText(device: AccountDevice) {
    val platformLabel = when (device.platform) {
        "android" -> stringResource(R.string.my_devices_platform_android)
        "web" -> stringResource(R.string.my_devices_platform_web)
        "iphone" -> stringResource(R.string.my_devices_platform_iphone)
        else -> device.platform
    }
    val lastSeen = if (device.lastSeenAt.isNullOrBlank()) {
        stringResource(R.string.my_devices_last_active_empty)
    } else {
        displayTime(device.lastSeenAt)
    }
    Text(
        text = stringResource(R.string.my_devices_row_platform_last_seen, platformLabel, lastSeen),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    if (device.isRevoked) {
        val revokedAt = if (device.revokedAt.isNullOrBlank()) {
            stringResource(R.string.my_devices_revoked_time_empty)
        } else {
            displayTime(device.revokedAt)
        }
        Text(
            text = stringResource(R.string.my_devices_row_revoked_at, revokedAt),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.error,
        )
    }
}

@Composable
private fun DeviceActionsRow(
    device: AccountDevice,
    busy: Boolean,
    actions: DeviceRowActions,
) {
    Row(
        horizontalArrangement = Arrangement.End,
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (!device.isRevoked) {
            TextButton(
                enabled = !busy,
                onClick = { actions.onRename(device) },
            ) {
                Text(stringResource(R.string.my_devices_action_rename))
            }
            if (!device.isCurrent) {
                TextButton(
                    enabled = !busy,
                    onClick = { actions.onRevoke(device) },
                ) {
                    Text(
                        text = stringResource(R.string.my_devices_action_revoke),
                        color = MaterialTheme.colorScheme.error,
                    )
                }
            }
        } else {
            TextButton(
                enabled = !busy,
                onClick = { actions.onDelete(device) },
            ) {
                Text(
                    text = stringResource(R.string.my_devices_action_delete),
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }
    }
}

/** Mint a one-time pairing code; the server stores only its hash. */
@Composable
private fun AddDeviceSection(
    creating: Boolean,
    createdCode: DevicePairingCode?,
    onCreate: () -> Unit,
    onDismissResult: () -> Unit,
) {
    SettingsSection(
        title = stringResource(R.string.my_devices_section_add),
        icon = Icons.Filled.GroupAdd,
    ) {
        SettingsOpenPanel(
            verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        ) {
            Text(
                text = stringResource(R.string.my_devices_add_intro),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            OutlinedButton(
                onClick = onCreate,
                enabled = !creating,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(
                    if (creating) {
                        stringResource(R.string.my_devices_add_creating)
                    } else {
                        stringResource(R.string.my_devices_add_create)
                    },
                )
            }
            createdCode?.let { code ->
                CreatedPairingCodeResult(code = code, onDismissResult = onDismissResult)
            }
        }
    }
}

@Composable
private fun CreatedPairingCodeResult(
    code: DevicePairingCode,
    onDismissResult: () -> Unit,
) {
    val clipboard = LocalClipboardManager.current
    Text(
        text = stringResource(R.string.my_devices_add_code_title),
        style = MaterialTheme.typography.titleSmall,
        color = MaterialTheme.colorScheme.onSurface,
    )
    Text(
        text = code.pairingCode,
        style = MaterialTheme.typography.headlineSmall,
        color = MaterialTheme.colorScheme.onSurface,
    )
    Text(
        text = stringResource(R.string.my_devices_add_code_expires_at, displayTime(code.expiresAt)),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Text(
        text = stringResource(R.string.my_devices_add_code_once_hint),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        OutlinedButton(
            onClick = { clipboard.setText(AnnotatedString(code.pairingCode)) },
            modifier = Modifier.weight(1f),
        ) {
            Text(stringResource(R.string.my_devices_add_code_copy))
        }
        TextButton(onClick = onDismissResult) {
            Text(stringResource(R.string.my_devices_add_code_dismiss))
        }
    }
}

@Composable
private fun RenameDeviceDialog(
    device: AccountDevice,
    onConfirm: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    var name by remember(device.publicId) { mutableStateOf(device.deviceName) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.my_devices_rename_dialog_title)) },
        text = {
            OutlinedTextField(
                value = name,
                onValueChange = { name = it },
                singleLine = true,
                label = { Text(stringResource(R.string.my_devices_rename_dialog_label)) },
            )
        },
        confirmButton = {
            TextButton(onClick = { onConfirm(name) }, enabled = name.isNotBlank()) {
                Text(stringResource(R.string.my_devices_rename_dialog_confirm))
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
private fun RevokeDeviceDialog(
    device: AccountDevice,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.my_devices_revoke_dialog_title)) },
        text = { Text(stringResource(R.string.my_devices_revoke_dialog_text, device.deviceName)) },
        confirmButton = {
            TextButton(onClick = onConfirm) {
                Text(
                    stringResource(R.string.my_devices_revoke_dialog_confirm),
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
private fun DeleteDeviceDialog(
    device: AccountDevice,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.my_devices_delete_dialog_title)) },
        text = { Text(stringResource(R.string.my_devices_delete_dialog_text, device.deviceName)) },
        confirmButton = {
            TextButton(onClick = onConfirm) {
                Text(
                    stringResource(R.string.my_devices_delete_dialog_confirm),
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

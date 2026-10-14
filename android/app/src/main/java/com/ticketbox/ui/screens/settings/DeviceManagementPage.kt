package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.AccountDevice
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.viewmodel.MyDevicesUiState
import com.ticketbox.viewmodel.MyDevicesViewModel

/** One nullable state enforces one device-management dialog at a time. */
internal sealed interface DeviceDialog {
    val device: AccountDevice

    data class Recover(override val device: AccountDevice) : DeviceDialog
    data class Revoke(override val device: AccountDevice) : DeviceDialog
    data class Remove(override val device: AccountDevice) : DeviceDialog
}

@Composable
internal fun DeviceManagementDialogHost(
    dialog: DeviceDialog?,
    viewModel: MyDevicesViewModel,
    activeLedgerId: String?,
    onDismiss: () -> Unit,
) {
    when (val open = dialog) {
        is DeviceDialog.Recover -> RecoverDeviceDialog(
            device = open.device,
            onConfirm = { viewModel.recover(open.device, activeLedgerId); onDismiss() },
            onDismiss = { onDismiss() },
        )
        is DeviceDialog.Revoke -> RevokeDeviceDialog(
            device = open.device,
            onConfirm = { viewModel.revoke(open.device, activeLedgerId); onDismiss() },
            onDismiss = { onDismiss() },
        )
        is DeviceDialog.Remove -> DeleteDeviceDialog(
            device = open.device,
            onConfirm = { viewModel.delete(open.device, activeLedgerId); onDismiss() },
            onDismiss = { onDismiss() },
        )
        null -> Unit
    }
}

@Composable
internal fun DeviceManagementPage(
    device: AccountDevice,
    state: MyDevicesUiState,
    rowActions: DeviceRowActions,
    actions: DeviceEditorActions,
) {
    var name by rememberSaveable(device.publicId) { mutableStateOf(device.deviceName) }
    val busy = state.busyDeviceId == device.publicId
    val current = state.devices.firstOrNull { it.publicId == device.publicId } ?: device
    LaunchedEffect(state.devices, state.messageTone) {
        if (state.messageTone == MessageTone.Success && state.devices.none { it.publicId == device.publicId }) actions.onBack()
    }
    ManagementPageFrame(
        header = ManagementPageHeader(device.deviceName, stringResource(R.string.my_devices_management_intro),
            ManagementPageChrome(backText = stringResource(R.string.my_devices_page_title))),
        onBack = { if (!busy) actions.onBack() },
        status = { AppStatusBanner(message = state.message, tone = state.messageTone) },
        bottomBar = { AppFloatingActionBar {
            AppPrimaryButton(stringResource(R.string.my_devices_rename_dialog_confirm),
                enabled = !busy && name.isNotBlank(), onClick = { actions.onSave(name) }, modifier = Modifier.fillMaxWidth())
        } },
    ) {
        SettingsDialogTextInput(SettingsTextInputState(label = stringResource(R.string.my_devices_rename_dialog_label),
            value = name, enabled = !busy), onValueChange = { name = it }, modifier = Modifier.fillMaxWidth())
        DeviceActivityText(current)
        Text(stringResource(R.string.my_devices_original_identity_hint), style = MaterialTheme.typography.bodyMedium)
        DeviceManagementActions(current, busy, rowActions)
        state.createdPairingCode?.let { CreatedPairingCodeResult(it, actions.onDismissCode) }
    }
}

internal data class DeviceEditorActions(val onSave: (String) -> Unit, val onBack: () -> Unit, val onDismissCode: () -> Unit)

@Composable
private fun DeviceManagementActions(device: AccountDevice, busy: Boolean, actions: DeviceRowActions) {
    if (!device.isCurrent) TextButton(onClick = { actions.onRecover(device) }, enabled = !busy) {
        Text(stringResource(R.string.my_devices_action_recover))
    }
    if (!device.isCurrent && !device.isRevoked) TextButton(onClick = { actions.onRevoke(device) }, enabled = !busy) {
        Text(stringResource(R.string.my_devices_action_revoke))
    }
    if (device.isRevoked) TextButton(onClick = { actions.onDelete(device) }, enabled = !busy) {
        Text(stringResource(R.string.my_devices_action_delete))
    }
}

@Composable
private fun RecoverDeviceDialog(
    device: AccountDevice,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.my_devices_recovery_dialog_title)) },
        text = { Text(stringResource(R.string.my_devices_recovery_dialog_text, device.deviceName)) },
        confirmButton = {
            TextButton(onClick = onConfirm) {
                Text(stringResource(R.string.my_devices_recovery_dialog_confirm))
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

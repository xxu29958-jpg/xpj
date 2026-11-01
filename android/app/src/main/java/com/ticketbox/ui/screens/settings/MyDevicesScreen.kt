package com.ticketbox.ui.screens.settings

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
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
import androidx.compose.material.icons.filled.MoreVert
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppOutlinedButtonOptions
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
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.res.vectorResource
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.style.TextOverflow
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.ticketbox.R
import com.ticketbox.domain.model.AccountDevice
import com.ticketbox.domain.model.DevicePairingCode
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.SettingsEntryIcon
import com.ticketbox.presentation.displayDateTime
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.MyDevicesUiState
import com.ticketbox.viewmodel.MyDevicesViewModel

/** Row management callbacks grouped so device rows stay small and stable. */
@Immutable
internal class DeviceRowActions(
    val onRename: (AccountDevice) -> Unit,
    val onRecover: (AccountDevice) -> Unit,
    val onRevoke: (AccountDevice) -> Unit,
    val onDelete: (AccountDevice) -> Unit,
)

@Composable
fun MyDevicesScreen(
    viewModel: MyDevicesViewModel,
    activeLedgerId: String?,
    onBack: () -> Unit,
    onOpenSecurity: () -> Unit,
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    var dialog by remember(activeLedgerId) { mutableStateOf<DeviceDialog?>(null) }
    var selectedDevice by remember(activeLedgerId) { mutableStateOf<AccountDevice?>(null) }
    val rowActions = remember(activeLedgerId, viewModel) {
        DeviceRowActions(
            onRename = { selectedDevice = it },
            onRecover = { dialog = DeviceDialog.Recover(it) },
            onRevoke = { dialog = DeviceDialog.Revoke(it) },
            onDelete = { dialog = DeviceDialog.Remove(it) },
        )
    }

    LaunchedEffect(activeLedgerId) { viewModel.refresh(activeLedgerId) }
    DisposableEffect(viewModel) { onDispose { viewModel.dismissPairingCode() } }
    BackHandler(enabled = selectedDevice != null && dialog == null) {
        if (state.busyDeviceId == null) { selectedDevice = null; viewModel.dismissPairingCode() }
    }

    DeviceManagementDialogHost(dialog, viewModel, activeLedgerId) { dialog = null }

    selectedDevice?.let { selected ->
        DeviceManagementPage(selected, state, rowActions, DeviceEditorActions(
            onSave = { name -> viewModel.rename(selected, name, activeLedgerId) { selectedDevice = null; viewModel.dismissPairingCode() } },
            onBack = { selectedDevice = null; viewModel.dismissPairingCode() },
            onDismissCode = viewModel::dismissPairingCode,
        ))
        return
    }

    SettingsPageFrame(
        title = stringResource(R.string.my_devices_page_title),
        subtitle = stringResource(R.string.my_devices_page_subtitle_manage),
        onBack = onBack,
        status = { AppStatusBanner(message = state.message, tone = state.messageTone) },
    ) {
        DeviceListSection(
            state = state,
            onRefresh = { viewModel.refresh(activeLedgerId) },
            actions = rowActions,
        )
        AddDeviceSection(
            creating = state.pairingCreating,
            createdCode = state.createdPairingCode,
            onCreate = { viewModel.createPairingCode(activeLedgerId) },
            onDismissResult = { viewModel.dismissPairingCode() },
        )
        SettingsEntryRow(stringResource(R.string.my_devices_session_entry), stringResource(R.string.my_devices_session_hint),
            R.drawable.ic_lucide_user_round_x, onClick = onOpenSecurity)
    }
}

@Composable
private fun DeviceListSection(
    state: MyDevicesUiState,
    onRefresh: () -> Unit,
    actions: DeviceRowActions,
) {
    SettingsSection(
        title = stringResource(R.string.my_devices_section_devices),
    ) {
        SettingsOpenPanel(
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            SettingsListStateSlot(
                loading = state.loading,
                hasData = state.devices.isNotEmpty(),
                copy = SettingsStateSlotCopy(
                    loadingTitle = stringResource(R.string.my_devices_loading_title),
                    loadingBody = stringResource(R.string.my_devices_loading_body),
                    emptyText = stringResource(R.string.my_devices_empty),
                ),
            )
            state.devices.forEachIndexed { index, device ->
                DeviceRow(
                    device = device,
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
    busy: Boolean,
    actions: DeviceRowActions,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clickable(enabled = !busy) { actions.onRename(device) }
            .padding(vertical = AppSpacing.miniGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        SettingsEntryIcon(ImageVector.vectorResource(when (device.platform) {
            "web" -> R.drawable.ic_lucide_monitor_smartphone
            "windows", "desktop" -> R.drawable.ic_lucide_monitor
            else -> R.drawable.ic_lucide_phone
        }))
        Spacer(Modifier.width(AppSpacing.contentGap))
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            DeviceTitleRow(device = device)
            DeviceActivityText(device = device)
        }
        DeviceActionsMenu(device = device, busy = busy, actions = actions)
    }
}

@Composable
private fun DeviceTitleRow(device: AccountDevice) {
    Row(verticalAlignment = Alignment.CenterVertically) {
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
            modifier = Modifier.weight(1f, fill = false),
        )
        if (device.isCurrent) {
            Spacer(Modifier.width(AppSpacing.miniGap + AppSpacing.tinyGap))
            Text(
                text = stringResource(R.string.my_devices_row_current_badge),
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.primary,
            )
        }
    }
}

@Composable
internal fun DeviceActivityText(device: AccountDevice) {
    val platformLabel = when (device.platform) {
        "android" -> stringResource(R.string.my_devices_platform_android)
        "web" -> stringResource(R.string.my_devices_platform_web)
        "iphone" -> stringResource(R.string.my_devices_platform_iphone)
        "windows" -> stringResource(R.string.my_devices_platform_windows)
        "desktop" -> stringResource(R.string.my_devices_platform_desktop)
        else -> device.platform
    }
    val lastSeen = if (device.lastSeenAt.isNullOrBlank()) {
        stringResource(R.string.my_devices_last_active_empty)
    } else {
        displayDateTime(device.lastSeenAt)
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
            displayDateTime(device.revokedAt)
        }
        Text(
            text = stringResource(R.string.my_devices_row_revoked_at, revokedAt),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.error,
        )
    }
}

@Composable
private fun DeviceActionsMenu(
    device: AccountDevice,
    busy: Boolean,
    actions: DeviceRowActions,
) {
    var expanded by remember(device.publicId) { mutableStateOf(false) }
    IconButton(
        enabled = !busy,
        onClick = { expanded = true },
    ) {
        Icon(
            imageVector = Icons.Filled.MoreVert,
            contentDescription = stringResource(R.string.my_devices_actions_content_description),
        )
    }
    DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
        DropdownMenuItem(
            text = { Text(stringResource(R.string.my_devices_action_rename)) },
            onClick = {
                expanded = false
                actions.onRename(device)
            },
        )
        if (!device.isCurrent) {
            DropdownMenuItem(
                text = { Text(stringResource(R.string.my_devices_action_recover)) },
                onClick = {
                    expanded = false
                    actions.onRecover(device)
                },
            )
        }
        if (!device.isCurrent && !device.isRevoked) {
            DropdownMenuItem(
                text = {
                    Text(
                        text = stringResource(R.string.my_devices_action_revoke),
                        color = MaterialTheme.colorScheme.error,
                    )
                },
                onClick = {
                    expanded = false
                    actions.onRevoke(device)
                },
            )
        }
        if (device.isRevoked) {
            DropdownMenuItem(
                text = {
                    Text(
                        text = stringResource(R.string.my_devices_action_delete),
                        color = MaterialTheme.colorScheme.error,
                    )
                },
                onClick = {
                    expanded = false
                    actions.onDelete(device)
                },
            )
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
    ) {
        SettingsOpenPanel(
            verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        ) {
            Text(
                text = stringResource(R.string.my_devices_add_intro),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            AppOutlinedButton(
                onClick = onCreate,
                options = AppOutlinedButtonOptions(enabled = !creating),
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

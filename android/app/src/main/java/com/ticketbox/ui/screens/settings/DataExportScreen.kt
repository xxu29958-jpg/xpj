package com.ticketbox.ui.screens.settings

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material.icons.outlined.Sync
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.viewmodel.SettingsUiState

@Composable
fun DataExportScreen(
    state: SettingsUiState,
    onBack: () -> Unit,
    onSync: () -> Unit,
    onClearCache: () -> Unit,
    portableDownload: @Composable () -> Unit,
) {
    var showClearCacheDialog by rememberSaveable { mutableStateOf(false) }
    if (showClearCacheDialog) {
        AlertDialog(
            onDismissRequest = { showClearCacheDialog = false },
            title = { Text(stringResource(R.string.settings_data_export_clear_dialog_title)) },
            text = { Text(stringResource(R.string.settings_data_export_clear_dialog_text)) },
            confirmButton = {
                TextButton(enabled = !state.busy, onClick = { showClearCacheDialog = false; onClearCache() }) {
                    Text(stringResource(R.string.settings_data_export_clear_dialog_confirm), color = MaterialTheme.colorScheme.error)
                }
            },
            dismissButton = { TextButton(onClick = { showClearCacheDialog = false }) { Text(stringResource(R.string.common_cancel)) } },
        )
    }
    SettingsPageFrame(
        title = stringResource(R.string.settings_data_export_page_title),
        subtitle = stringResource(R.string.settings_data_export_page_subtitle),
        onBack = onBack,
        status = { AppStatusBanner(message = state.message, tone = state.messageTone) },
    ) {
        SettingsSection(title = stringResource(R.string.settings_data_export_server_section)) { portableDownload() }
        SettingsSection(title = stringResource(R.string.settings_data_export_section_refresh_cache)) {
            SettingsDataRow(
                title = stringResource(R.string.settings_data_export_button_refresh),
                subtitle = stringResource(R.string.settings_data_export_refresh_hint), icon = Icons.Outlined.Sync,
                action = SettingsDataAction(stringResource(if (state.busy) R.string.settings_data_export_button_refreshing
                    else R.string.settings_data_export_refresh_action)), onClick = if (state.busy) null else onSync,
            )
            SettingsDataRow(
                title = stringResource(R.string.settings_data_export_clear_row_title),
                subtitle = stringResource(R.string.settings_data_export_clear_row_body), icon = Icons.Outlined.Storage,
                action = SettingsDataAction(stringResource(R.string.settings_data_export_clear_row_action)),
                onClick = if (state.busy) null else { { showClearCacheDialog = true } },
            )
        }
        SettingsDataNote(stringResource(R.string.settings_data_export_pending_title),
            stringResource(R.string.settings_data_export_pending_body))
    }
}

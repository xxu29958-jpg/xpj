package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.SettingsUiState

@Composable
fun ServerSettingsScreen(
    state: SettingsUiState,
    showAdvancedTools: Boolean,
    onBack: () -> Unit,
    onTestConnection: () -> Unit,
    onRunDiagnostics: () -> Unit,
    onRefreshServerSettings: () -> Unit,
    onSync: () -> Unit,
) {
    var showDiagnosticsDetails by remember { mutableStateOf(false) }
    val pageTitle = if (showAdvancedTools) {
        stringResource(R.string.settings_server_page_title_advanced)
    } else {
        stringResource(R.string.settings_server_page_title_basic)
    }
    val pageSubtitle = if (showAdvancedTools) {
        stringResource(R.string.settings_server_page_subtitle_advanced)
    } else {
        stringResource(R.string.settings_server_page_subtitle_basic)
    }
    SettingsPageFrame(
        title = pageTitle,
        subtitle = pageSubtitle,
        onBack = onBack,
        status = { AppStatusBanner(message = state.message, tone = state.messageTone) },
    ) {
        AccountStatusCard(
            serverSettings = state.serverSettings,
            serverUrl = state.serverUrl,
            accountName = state.accountName,
            ledgerName = state.ledgerName,
            deviceName = state.deviceName,
            role = state.role,
            lastUploadAt = state.lastUploadAt,
            lastSyncAt = state.lastConfirmedSyncAt,
            busy = state.busy,
            onCheckConnection = onTestConnection,
            onSync = {
                onSync()
                onRefreshServerSettings()
            },
        )
        if (showAdvancedTools) {
            SettingsSection(title = stringResource(R.string.settings_server_section_internal_tools), icon = Icons.Filled.Settings) {
                Text(
                    text = stringResource(R.string.settings_server_internal_tools_hint),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        enabled = !state.busy,
                        onClick = onRunDiagnostics,
                    ) {
                        Text(stringResource(R.string.settings_server_button_run_diagnostics))
                    }
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        enabled = !state.busy,
                        onClick = onRefreshServerSettings,
                    ) {
                        Text(stringResource(R.string.settings_server_button_refresh_settings))
                    }
                }
                AdvancedStatusCard(
                    diagnostics = state.diagnostics,
                    expanded = showDiagnosticsDetails,
                    onToggleExpanded = { showDiagnosticsDetails = !showDiagnosticsDetails },
                )
            }
        }
    }
}

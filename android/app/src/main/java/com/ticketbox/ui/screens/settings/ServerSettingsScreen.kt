package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
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

@Immutable
data class ServerSettingsScreenState(
    val settings: SettingsUiState,
    val showAdvancedTools: Boolean,
)

@Immutable
data class ServerSettingsScreenActions(
    val onBack: () -> Unit,
    val onTestConnection: () -> Unit,
    val onRunDiagnostics: () -> Unit,
    val onRefreshServerSettings: () -> Unit,
    val onSync: () -> Unit,
)

@Composable
fun ServerSettingsScreen(
    state: ServerSettingsScreenState,
    actions: ServerSettingsScreenActions,
) {
    val settings = state.settings
    var showDiagnosticsDetails by remember { mutableStateOf(false) }
    val pageTitle = if (state.showAdvancedTools) {
        stringResource(R.string.settings_server_page_title_advanced)
    } else {
        stringResource(R.string.settings_server_page_title_basic)
    }
    val pageSubtitle = if (state.showAdvancedTools) {
        stringResource(R.string.settings_server_page_subtitle_advanced)
    } else {
        stringResource(R.string.settings_server_page_subtitle_basic)
    }
    SettingsPageFrame(
        title = pageTitle,
        subtitle = pageSubtitle,
        onBack = actions.onBack,
        status = { AppStatusBanner(message = settings.message, tone = settings.messageTone) },
    ) {
        AccountStatusCard(
            state = AccountStatusCardState(
                serverSettings = settings.confirmedServerSettings(),
                serverUrl = settings.serverUrl,
                accountName = settings.accountName,
                ledgerName = settings.ledgerName,
                deviceName = settings.deviceName,
                role = settings.role,
                lastUploadAt = settings.lastUploadAt,
                lastSyncAt = settings.lastConfirmedSyncAt,
                busy = settings.busy,
            ),
            actions = AccountStatusCardActions(
                onCheckConnection = actions.onTestConnection,
                onSync = {
                    actions.onSync()
                    actions.onRefreshServerSettings()
                },
            ),
        )
        if (state.showAdvancedTools) {
            SettingsSection(title = stringResource(R.string.settings_server_section_internal_tools), icon = Icons.Filled.Settings) {
                Text(
                    text = stringResource(R.string.settings_server_internal_tools_hint),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
                Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        enabled = !settings.busy,
                        onClick = actions.onRunDiagnostics,
                    ) {
                        Text(stringResource(R.string.settings_server_button_run_diagnostics))
                    }
                    OutlinedButton(
                        modifier = Modifier.weight(1f),
                        enabled = !settings.busy,
                        onClick = actions.onRefreshServerSettings,
                    ) {
                        Text(stringResource(R.string.settings_server_button_refresh_settings))
                    }
                }
                AdvancedStatusCard(
                    diagnostics = settings.diagnostics,
                    expanded = showDiagnosticsDetails,
                    onToggleExpanded = { showDiagnosticsDetails = !showDiagnosticsDetails },
                )
            }
        }
    }
}

internal fun SettingsUiState.confirmedServerSettings() = serverSettings.takeIf { serverSettingsFresh }

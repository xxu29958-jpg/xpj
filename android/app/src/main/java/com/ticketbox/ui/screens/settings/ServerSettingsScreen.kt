package com.ticketbox.ui.screens.settings

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material.icons.filled.CloudDone
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.displayTime
import com.ticketbox.viewmodel.SettingsUiState

@Immutable
data class ServerSettingsScreenState(
    val settings: SettingsUiState,
    val showAdvancedTools: Boolean,
)

@Immutable
data class ServerSettingsScreenActions(
    val onBack: () -> Unit,
    val onRunDiagnostics: () -> Unit,
    val onCancelConnectionWork: () -> Unit,
    val onRefreshServerSettings: () -> Unit,
    val onSync: () -> Unit,
    val onOpenSyncStatus: () -> Unit,
)

@Composable
fun ServerSettingsScreen(
    state: ServerSettingsScreenState,
    actions: ServerSettingsScreenActions,
) {
    val settings = state.settings
    var showDiagnosticsDetails by remember(settings.access?.binding) { mutableStateOf(false) }
    LaunchedEffect(settings.access?.binding) { actions.onRefreshServerSettings() }
    DisposableEffect(Unit) { onDispose { actions.onCancelConnectionWork() } }
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
        BackupRecordSection(settings, actions.onRefreshServerSettings)
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
                onCheckConnection = actions.onRunDiagnostics,
                onSync = actions.onSync,
            ),
        )
        SettingsSection(title = stringResource(R.string.settings_server_section_diagnostics)) {
            Text(
                text = stringResource(R.string.settings_server_diagnostics_hint),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            ConnectionDiagnosticsCard(
                diagnostics = settings.diagnostics,
                expanded = showDiagnosticsDetails,
                showTiming = state.showAdvancedTools,
                onToggleExpanded = { showDiagnosticsDetails = !showDiagnosticsDetails },
            )
            OutlinedButton(onClick = actions.onOpenSyncStatus) {
                Text(stringResource(R.string.settings_server_open_pending_operations))
            }
            if (state.showAdvancedTools) {
                OutlinedButton(
                    enabled = !settings.busy,
                    onClick = actions.onRefreshServerSettings,
                ) {
                    Text(stringResource(R.string.settings_server_button_refresh_settings))
                }
            }
        }
    }
}

@Composable
private fun BackupRecordSection(state: SettingsUiState, onRefresh: () -> Unit) {
    SettingsSection(title = stringResource(R.string.settings_backup_title)) {
        val health = state.backupHealth
        when {
            state.backupLoading -> Text(stringResource(R.string.settings_backup_loading))
            state.backupError != null -> AppStatusBanner(message = state.backupError,
                tone = com.ticketbox.domain.model.MessageTone.Danger)
            health == null -> Text(stringResource(R.string.settings_backup_read_failed))
            health.latestBackupAt == null -> Text(stringResource(R.string.settings_backup_never))
            else -> {
                Text(stringResource(R.string.settings_backup_latest, displayTime(health.latestBackupAt)))
                health.ageHours?.let { Text(stringResource(R.string.settings_backup_age_hours, it)) }
                Text(stringResource(if (health.stale) R.string.settings_backup_stale else R.string.settings_backup_recent))
            }
        }
        Text(stringResource(R.string.settings_backup_next_step), style = MaterialTheme.typography.bodyMedium)
        Text(stringResource(R.string.settings_backup_record_scope), style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        OutlinedButton(onClick = onRefresh, enabled = !state.busy && !state.backupLoading) {
            Text(stringResource(R.string.settings_backup_refresh))
        }
    }
}

internal fun SettingsUiState.confirmedServerSettings() = serverSettings.takeIf { serverSettingsFresh }

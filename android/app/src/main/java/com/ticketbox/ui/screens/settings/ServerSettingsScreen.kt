package com.ticketbox.ui.screens.settings

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.outlined.Inventory2
import androidx.compose.material.icons.outlined.VpnKey
import androidx.compose.material.icons.outlined.Wifi
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.DiagnosticCheckKind
import com.ticketbox.domain.model.DiagnosticStatus
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppPageChrome
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPageScrollableColumn
import com.ticketbox.ui.components.AppScrollablePageChrome
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.design.AppAdaptiveContentWidth
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.SettingsUiState

@Immutable
data class ServerSettingsScreenState(val settings: SettingsUiState, val showAdvancedTools: Boolean)

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
fun ServerSettingsScreen(state: ServerSettingsScreenState, actions: ServerSettingsScreenActions) {
    val settings = state.settings
    BackHandler(onBack = actions.onBack)
    LaunchedEffect(settings.access?.binding) { actions.onRefreshServerSettings() }
    DisposableEffect(Unit) { onDispose { actions.onCancelConnectionWork() } }
    AppPageScrollableColumn(
        chrome = AppScrollablePageChrome(
            page = AppPageChrome(role = AppPageRole.Settings, hasBottomBar = false),
            contentWidth = AppAdaptiveContentWidth.Secondary,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap),
        ),
        bottomBar = {
            Surface(color = MaterialTheme.colorScheme.background) {
                SettingsPrimaryAction(
                    text = stringResource(if (settings.busy) R.string.settings_account_button_busy
                        else R.string.settings_server_check_again),
                    enabled = !settings.busy,
                    modifier = Modifier.fillMaxWidth().navigationBarsPadding()
                        .padding(horizontal = AppSpacing.screenHorizontal, vertical = AppSpacing.contentGap),
                    onClick = actions.onRunDiagnostics,
                )
            }
        },
    ) {
        SettingsPageHeading(stringResource(R.string.settings_server_page_title_basic),
            stringResource(R.string.settings_server_page_subtitle_basic), actions.onBack)
        AppStatusBanner(message = settings.message, tone = settings.messageTone)
        ConnectionLayerEntries(state, actions)
        BackupRecordSection(settings, actions.onRefreshServerSettings)
        SettingsDataNote(stringResource(R.string.settings_backup_note_title), stringResource(R.string.settings_backup_note_body))
    }
}

@Composable
private fun ConnectionLayerEntries(state: ServerSettingsScreenState, actions: ServerSettingsScreenActions) {
    val settings = state.settings
    var showDiagnostics by rememberSaveable(settings.access?.binding) { mutableStateOf(false) }
    var showIdentity by rememberSaveable(settings.access?.binding) { mutableStateOf(false) }
    val result = settings.diagnostics
    val reachable = if (result == null) settings.confirmedServerSettings() != null
        else result.checks.any { it.status == DiagnosticStatus.Pass }
    val identityConfirmed = if (result == null) settings.confirmedServerSettings() != null
        else result.checks.any { it.kind == DiagnosticCheckKind.Auth && it.status == DiagnosticStatus.Pass }
    Column {
        SettingsDataRow(
            title = stringResource(R.string.settings_server_reachability_title),
            subtitle = stringResource(if (reachable) R.string.settings_server_reachability_confirmed else R.string.settings_server_reachability_unknown),
            icon = Icons.Outlined.Wifi,
            action = SettingsDataAction(stringResource(if (reachable) R.string.settings_server_reachable else R.string.settings_server_unconfirmed), reachable),
            onClick = { showDiagnostics = !showDiagnostics },
        )
        if (showDiagnostics || result?.checks?.any { it.status != DiagnosticStatus.Pass } == true) {
            ConnectionDiagnosticsCard(result, showDiagnostics, state.showAdvancedTools, onToggleExpanded = { showDiagnostics = !showDiagnostics })
            Text(stringResource(R.string.settings_server_diagnostics_hint), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        SettingsDataRow(
            title = stringResource(R.string.settings_server_identity_title),
            subtitle = stringResource(if (identityConfirmed) R.string.settings_server_identity_confirmed else R.string.settings_server_identity_unknown),
            icon = Icons.Outlined.VpnKey,
            action = SettingsDataAction(stringResource(if (identityConfirmed) R.string.settings_server_valid else R.string.settings_server_unconfirmed), identityConfirmed),
            onClick = { showIdentity = !showIdentity },
        )
        if (showIdentity) ConnectionIdentityDetails(state, actions)
        SettingsDataRow(
            title = stringResource(R.string.settings_server_pending_title),
            subtitle = stringResource(R.string.settings_server_pending_hint), icon = Icons.AutoMirrored.Outlined.Send,
            action = SettingsDataAction(stringResource(R.string.settings_server_open_action)), onClick = actions.onOpenSyncStatus,
        )
    }
}

@Composable
private fun ConnectionIdentityDetails(state: ServerSettingsScreenState, actions: ServerSettingsScreenActions) {
    val settings = state.settings
    AccountStatusCard(
        state = AccountStatusCardState(
            serverSettings = settings.confirmedServerSettings(), serverUrl = settings.serverUrl,
            accountName = settings.accountName, ledgerName = settings.ledgerName, deviceName = settings.deviceName,
            role = settings.role, lastUploadAt = settings.lastUploadAt, lastSyncAt = settings.lastConfirmedSyncAt, busy = settings.busy,
        ),
        actions = AccountStatusCardActions(onCheckConnection = actions.onRunDiagnostics, onSync = actions.onSync),
    )
    if (state.showAdvancedTools) OutlinedButton(enabled = !settings.busy, onClick = actions.onRefreshServerSettings) {
        Text(stringResource(R.string.settings_server_button_refresh_settings))
    }
}

@Composable
private fun BackupRecordSection(state: SettingsUiState, onRefresh: () -> Unit) {
    var expanded by rememberSaveable(state.access?.binding) { mutableStateOf(false) }
    val health = state.backupHealth
    SettingsSection(title = stringResource(R.string.settings_backup_title)) {
        SettingsDataRow(
            title = stringResource(R.string.settings_backup_latest_title), subtitle = backupRecordSummary(state), icon = Icons.Outlined.Inventory2,
            action = SettingsDataAction(stringResource(if (expanded) R.string.settings_account_toggle_collapse
                else R.string.settings_backup_view)), onClick = { expanded = !expanded },
        )
        if (expanded) {
            if (state.backupError != null) AppStatusBanner(message = state.backupError, tone = MessageTone.Danger)
            else if (!state.backupLoading && health == null) Text(stringResource(R.string.settings_backup_read_failed))
            if (!state.backupLoading && state.backupError == null && health?.latestBackupAt != null) {
                health.ageHours?.let { Text(stringResource(R.string.settings_backup_age_hours, it)) }
                Text(stringResource(if (health.stale) R.string.settings_backup_stale else R.string.settings_backup_recent))
            }
            Text(stringResource(R.string.settings_backup_next_step), style = MaterialTheme.typography.bodyMedium)
            Text(stringResource(R.string.settings_backup_record_scope), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            OutlinedButton(onClick = onRefresh, enabled = !state.busy && !state.backupLoading) {
                Text(stringResource(R.string.settings_backup_refresh))
            }
        }
    }
}

@Composable
private fun backupRecordSummary(state: SettingsUiState): String {
    val health = state.backupHealth
    return when {
        state.backupLoading -> stringResource(R.string.settings_backup_loading)
        state.backupError != null || health == null -> stringResource(R.string.settings_backup_unconfirmed)
        health.latestBackupAt == null -> stringResource(R.string.settings_backup_never)
        else -> stringResource(R.string.settings_backup_latest, displayTime(health.latestBackupAt))
    }
}

internal fun SettingsUiState.confirmedServerSettings() = serverSettings.takeIf { serverSettingsFresh }

package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.KeyboardArrowRight
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import com.ticketbox.R
import com.ticketbox.domain.model.ledgerRoleLabel
import com.ticketbox.ui.components.displayTime
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.SettingsUiState

@Composable
internal fun SettingsRootAccountSummary(
    state: SettingsUiState,
    onOpenConnection: () -> Unit,
) {
    val data = settingsRootAccountSummaryData(state)
    SettingsRootAccountSummaryLayout(data = data, onOpenConnection = onOpenConnection)
}

@Composable
private fun settingsRootAccountSummaryData(state: SettingsUiState): SettingsRootAccountSummaryData {
    val serverSettings = state.serverSettings.takeIf { state.serverSettingsFresh }
    val displayAccount = firstNotBlank(serverSettings?.accountName, state.accountName)
        ?: stringResource(R.string.settings_account_default_account)
    val displayLedger = firstNotBlank(serverSettings?.ledgerName, state.ledgerName)
        ?: stringResource(R.string.settings_account_default_ledger)
    val displayDevice = firstNotBlank(serverSettings?.deviceName, state.deviceName)
        ?: stringResource(R.string.settings_account_default_device)
    val roleCode = firstNotBlank(serverSettings?.role, state.role)
    val displayRole = roleCode?.let { ledgerRoleLabel(it) }
        ?: stringResource(R.string.settings_account_role_unknown)
    return SettingsRootAccountSummaryData(
        header = SettingsRootAccountHeaderData(
            ledger = displayLedger,
            status = settingsRootAccountStatus(state.busy, state.serverSettingsFresh),
            serverConfirmed = state.serverSettingsFresh,
        ),
        identity = stringResource(R.string.settings_root_account_identity_line, displayAccount, displayRole, displayDevice),
        lastSync = settingsRootLastSyncText(state.lastConfirmedSyncAt),
    )
}

@Composable
private fun SettingsRootAccountSummaryLayout(
    data: SettingsRootAccountSummaryData,
    onOpenConnection: () -> Unit,
) {
    SettingsOpenPanel(
        modifier = Modifier.clickable(onClick = onOpenConnection),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        SettingsRootAccountHeader(data.header)
        Text(
            text = data.identity,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
        Text(
            text = data.lastSync,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
        )
    }
}

@Composable
private fun SettingsRootAccountHeader(data: SettingsRootAccountHeaderData) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(
            modifier = Modifier.weight(1f),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            Text(
                text = stringResource(R.string.settings_account_current_ledger_label),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.labelMedium,
            )
            Text(
                text = data.ledger,
                style = MaterialTheme.typography.headlineSmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
            )
        }
        StatusPill(text = data.status, confirmed = data.serverConfirmed)
        Icon(
            imageVector = Icons.AutoMirrored.Filled.KeyboardArrowRight,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.size(AppSpacing.cardPadding),
        )
    }
}

@Composable
private fun settingsRootAccountStatus(busy: Boolean, fresh: Boolean): String = when {
    busy -> stringResource(R.string.settings_account_status_updating)
    fresh -> stringResource(R.string.settings_account_status_server_confirmed)
    else -> stringResource(R.string.settings_account_status_local_cache)
}

@Composable
private fun settingsRootLastSyncText(lastConfirmedSyncAt: String?): String = stringResource(
    R.string.settings_account_last_sync_line,
    lastConfirmedSyncAt?.let { displayTime(it) }
        ?: stringResource(R.string.settings_account_no_sync),
)

private fun firstNotBlank(vararg values: String?): String? =
    values.firstOrNull { !it.isNullOrBlank() }

private data class SettingsRootAccountSummaryData(
    val header: SettingsRootAccountHeaderData,
    val identity: String,
    val lastSync: String,
)

private data class SettingsRootAccountHeaderData(
    val ledger: String,
    val status: String,
    val serverConfirmed: Boolean,
)

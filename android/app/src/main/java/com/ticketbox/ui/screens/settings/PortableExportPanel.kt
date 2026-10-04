package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.selection.selectable
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FileDownload
import androidx.compose.material.icons.outlined.FileDownload
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import com.ticketbox.R
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.PortableExportStage
import com.ticketbox.viewmodel.PortableExportUiState

@Composable
internal fun PortableExportPanel(
    state: PortableExportUiState,
    onSelect: (String) -> Unit,
    onSave: () -> Unit,
    onCancel: () -> Unit,
    onRefresh: () -> Unit,
) {
    val idle = state.stage == PortableExportStage.Idle
    var expanded by rememberSaveable(state.binding) { mutableStateOf(false) }
    LaunchedEffect(state.stage, state.message) {
        if (!idle || state.message != null) expanded = true
    }
    SettingsDataRow(
        title = stringResource(R.string.portable_export_title),
        subtitle = stringResource(R.string.portable_export_entry_hint), icon = Icons.Outlined.FileDownload,
        action = SettingsDataAction(stringResource(if (expanded) R.string.settings_account_toggle_collapse
            else R.string.portable_export_entry_action)),
        onClick = if (idle) { { expanded = !expanded } } else null,
    )
    if (expanded) Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        Text(stringResource(R.string.portable_export_scope), style = MaterialTheme.typography.bodyMedium)
        AppStatusBanner(message = state.message, tone = state.tone)
        if (state.loading) Text(stringResource(R.string.portable_export_loading))
        else if (state.ledgers.isEmpty() && state.message == null) Text(stringResource(R.string.portable_export_empty))
        state.ledgers.forEach { ledger ->
            Row(modifier = Modifier.fillMaxWidth().selectable(
                selected = state.selectedLedgerId == ledger.ledgerId, enabled = idle,
                role = Role.RadioButton, onClick = { onSelect(ledger.ledgerId) },
            ).padding(vertical = AppSpacing.smallGap), verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
                RadioButton(selected = state.selectedLedgerId == ledger.ledgerId, onClick = null, enabled = idle)
                Column(Modifier.weight(1f)) {
                    Text(ledger.name, style = MaterialTheme.typography.titleSmall)
                    if (ledger.archivedAt != null) Text(stringResource(R.string.portable_export_archived),
                        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
        PortableSaveControls(state, onSave, onCancel)
        if (idle) TextButton(onClick = onRefresh, enabled = !state.loading) {
            Text(stringResource(R.string.portable_export_refresh))
        }
    }
}

@Composable
private fun PortableSaveControls(state: PortableExportUiState, onSave: () -> Unit, onCancel: () -> Unit) {
    when (state.stage) {
        PortableExportStage.Idle -> AppPrimaryButton(text = stringResource(R.string.portable_export_save),
            icon = Icons.Filled.FileDownload, modifier = Modifier.fillMaxWidth(),
            enabled = !state.loading && state.selectedLedgerId != null, onClick = onSave)
        PortableExportStage.ChoosingLocation -> Text(stringResource(R.string.portable_export_choosing))
        PortableExportStage.Downloading -> {
            Text(if (state.bytesWritten == 0L) stringResource(R.string.portable_export_preparing)
                else stringResource(R.string.portable_export_progress, state.bytesWritten / 1024))
            TextButton(onClick = onCancel) { Text(stringResource(R.string.common_cancel)) }
        }
    }
}

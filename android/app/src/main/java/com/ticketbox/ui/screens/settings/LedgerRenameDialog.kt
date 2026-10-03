package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.LedgerSwitcherUiState

@Composable
internal fun LedgerRenameDialog(state: LedgerSwitcherUiState, onNameChange: (String) -> Unit,
    onDismiss: () -> Unit, onSave: () -> Unit, onRefresh: () -> Unit) {
    val draft = state.rename ?: return
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.ledger_name_edit)) },
        text = {
            Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                Text(stringResource(R.string.ledger_name_current, draft.ledger.name))
                Text(stringResource(R.string.ledger_name_online_hint))
                AppStatusBanner(message = state.message, tone = state.messageTone)
                SettingsDialogTextInput(SettingsTextInputState(label = stringResource(R.string.ledger_switcher_field_ledger_name),
                    value = draft.name, enabled = !state.loading), onValueChange = onNameChange)
                if (!draft.fresh) {
                    Text(stringResource(if (draft.ledger.role == "owner") R.string.ledger_name_reload_hint else R.string.ledger_name_owner_only))
                    TextButton(onClick = onRefresh, enabled = !state.loading) { Text(stringResource(R.string.ledger_switcher_refresh_button)) }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onSave, enabled = !state.loading && draft.fresh && draft.name.isNotBlank()) {
                Text(stringResource(R.string.ledger_name_save))
            }
        },
        dismissButton = { TextButton(onClick = onDismiss, enabled = !state.loading) { Text(stringResource(R.string.common_cancel)) } },
    )
}

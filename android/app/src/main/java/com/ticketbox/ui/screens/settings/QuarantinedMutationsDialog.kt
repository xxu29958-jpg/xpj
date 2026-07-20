package com.ticketbox.ui.screens.settings

import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R

@Composable
internal fun ClearQuarantinedDialog(
    count: Int,
    busy: Boolean,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.sync_status_quarantined_remove_dialog_title)) },
        text = { Text(stringResource(R.string.sync_status_quarantined_remove_dialog_text, count)) },
        confirmButton = {
            TextButton(enabled = !busy, onClick = onConfirm) {
                Text(
                    text = stringResource(R.string.sync_status_quarantined_remove_dialog_confirm),
                    color = MaterialTheme.colorScheme.error,
                )
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.common_cancel)) }
        },
    )
}

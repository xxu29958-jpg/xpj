package com.ticketbox.ui.screens.budget

import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.viewmodel.BudgetUiState

@Composable
internal fun BudgetArchiveAction(state: BudgetUiState, onArchive: (Long) -> Unit) {
    var version by remember(state.binding, state.month) { mutableStateOf<Long?>(null) }
    val budget = state.budget
    val enabled = state.canModify && !state.saving && !state.hasPendingSave && !state.loading
    if (state.canModify && budget?.configured == true && budget.rowVersion != null) {
        TextButton(onClick = { version = budget.rowVersion }, enabled = enabled) {
            Text(stringResource(R.string.budget_archive_action))
        }
    }
    version?.let { originalVersion ->
        AlertDialog(onDismissRequest = { version = null },
            title = { Text(stringResource(R.string.budget_archive_title)) },
            text = { Text(stringResource(R.string.budget_archive_body, state.month)) },
            confirmButton = { TextButton(enabled = enabled, onClick = { version = null; onArchive(originalVersion) }) {
                Text(stringResource(R.string.budget_archive_confirm))
            } },
            dismissButton = { TextButton(onClick = { version = null }) { Text(stringResource(R.string.common_cancel)) } })
    }
}

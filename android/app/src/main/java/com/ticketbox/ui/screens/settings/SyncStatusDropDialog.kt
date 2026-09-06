package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.PendingDebtCreation
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.DebtCreationIntentSummary

/** Immutable user selection; a queue refresh cannot relabel an open discard confirmation. */
internal data class SyncStatusDropSelection(
    val row: OutboxRow,
    val failed: Boolean,
    val debtCreation: PendingDebtCreation?,
    val recurringOccurrence: com.ticketbox.data.repository.PendingOccurrencePayment? = null,
)

private data class DropConfirmationText(val title: String, val text: String, val confirmWord: String)

@Composable
internal fun SyncStatusDropDialog(
    selection: SyncStatusDropSelection,
    busy: Boolean,
    onConfirm: () -> Unit,
    onDismiss: () -> Unit,
) {
    val copy = dropConfirmationText(selection)
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(copy.title) },
        text = {
            Column(
                modifier = Modifier.verticalScroll(rememberScrollState()),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            ) {
                selection.debtCreation?.let { DebtCreationIntentSummary(it) }
                selection.recurringOccurrence?.let { com.ticketbox.ui.screens.recurring.RecurringOccurrenceIntentSummary(it) }
                Text(copy.text)
            }
        },
        confirmButton = {
            TextButton(enabled = !busy, onClick = onConfirm) {
                Text(copy.confirmWord, color = MaterialTheme.colorScheme.error)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) { Text(stringResource(R.string.common_cancel)) }
        },
    )
}

@Composable
private fun dropConfirmationText(selection: SyncStatusDropSelection): DropConfirmationText {
    val row = selection.row
    val expired = selection.failed && isExpiredFailure(row.lastError)
    val debtCreation = row.type == PendingMutationType.CreateDebt
    val label = stringResource(syncStatusMutationLabelRes(row.type))
    return when {
        row.type == PendingMutationType.SetRecurringOccurrencePayment -> DropConfirmationText(
            stringResource(R.string.occurrence_drop),
            stringResource(R.string.occurrence_drop_explanation),
            stringResource(R.string.occurrence_drop),
        )
        !selection.failed -> DropConfirmationText(
            stringResource(R.string.sync_status_conflict_drop_dialog_title),
            stringResource(R.string.sync_status_conflict_drop_dialog_text, label),
            stringResource(R.string.sync_status_drop_dialog_confirm),
        )
        expired -> DropConfirmationText(
            stringResource(R.string.sync_status_failed_drop_dialog_title_expired),
            if (debtCreation) stringResource(R.string.debt_create_expired_drop_dialog_text)
            else stringResource(R.string.sync_status_failed_drop_dialog_text_expired, label),
            stringResource(R.string.sync_status_drop_dialog_confirm_remove),
        )
        else -> DropConfirmationText(
            if (debtCreation) stringResource(R.string.debt_create_drop_dialog_title)
            else stringResource(R.string.sync_status_failed_drop_dialog_title),
            if (debtCreation) stringResource(R.string.debt_create_drop_dialog_text)
            else stringResource(R.string.sync_status_failed_drop_dialog_text, label),
            stringResource(R.string.sync_status_drop_dialog_confirm),
        )
    }
}

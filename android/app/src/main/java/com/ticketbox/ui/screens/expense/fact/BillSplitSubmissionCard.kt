package com.ticketbox.ui.screens.expense.fact

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.PendingBillSplitCreation
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.settings.friendlyLastError

/** The same original-intent card serves the source fact and global recovery. */
@Composable
internal fun BillSplitSubmissionCard(
    pending: PendingBillSplitCreation,
    canModify: Boolean,
    busy: Boolean,
    recover: (Boolean) -> Unit,
) {
    var confirmDrop by rememberSaveable(pending.row.id) { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        HorizontalDivider()
        Text(stringResource(R.string.sync_status_mutation_create_bill_split))
        pending.payload?.let { original ->
            Text(original.merchant.orEmpty())
            Text(stringResource(R.string.bill_split_submission_recipient, original.receiverName,
                formatDisplayAmount(original.request.amountCents, CurrencyDisplay.forRecord(original.homeCurrencyCode))))
        }
        Text(when {
            pending.payload == null -> stringResource(R.string.bill_split_submission_unsupported)
            pending.row.lastError == "bill_split_requires_review" -> stringResource(R.string.bill_split_submission_review)
            pending.row.status == PendingMutationStatus.Pending || pending.row.status == PendingMutationStatus.InFlight ->
                stringResource(R.string.bill_split_submission_waiting)
            else -> friendlyLastError(pending.row.lastError, stringResource(R.string.expense_edit_bill_split_send_failed))
        })
        if (pending.canRetry && canModify) TextButton(onClick = { recover(false) }, enabled = !busy) {
            Text(stringResource(R.string.correction_submission_retry))
        }
        if (pending.row.status == PendingMutationStatus.Failed) TextButton(onClick = { confirmDrop = true }, enabled = !busy) {
            Text(stringResource(R.string.bill_split_submission_stop))
        }
    }
    if (confirmDrop) AlertDialog(
        onDismissRequest = { confirmDrop = false },
        title = { Text(stringResource(R.string.bill_split_submission_stop)) },
        text = { Text(stringResource(R.string.bill_split_submission_stop_explanation)) },
        confirmButton = { TextButton(onClick = { confirmDrop = false; recover(true) }) {
            Text(stringResource(R.string.bill_split_submission_stop))
        } },
        dismissButton = { TextButton(onClick = { confirmDrop = false }) { Text(stringResource(android.R.string.cancel)) } },
    )
}

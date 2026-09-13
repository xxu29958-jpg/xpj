package com.ticketbox.ui.screens.settings

import androidx.compose.material3.MaterialTheme
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CloudUpload
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.ManualExpenseCreationProjection
import com.ticketbox.data.repository.expenseLocalTargetId
import com.ticketbox.viewmodel.OutboxStatusUiState

@Composable
internal fun ManualCreationSubmissionSection(state: OutboxStatusUiState, actions: SyncStatusActions, focusedRef: String?) {
    val originals = state.manualCreations.values.filter {
        if (focusedRef != null) it.row.targetId == expenseLocalTargetId(focusedRef)
        else it.row.status != PendingMutationStatus.Done
    }
    if (focusedRef != null && originals.isEmpty()) Text(stringResource(R.string.manual_submission_missing))
    originals.forEach { original ->
        SettingsSection(title = stringResource(R.string.manual_submission_title), icon = Icons.Filled.CloudUpload) {
            ManualCreationOriginalSummary(original)
            when (original.row.status) {
                PendingMutationStatus.Failed -> FailedCard(original.row, null, state.busyRowId == original.row.id,
                    { actions.onRetry(original.row) }.takeIf { state.offersRetry(original.row) }, actions)
                PendingMutationStatus.Conflict -> ConflictCard(original.row, state.busyRowId == original.row.id, actions)
                PendingMutationStatus.Done -> {
                    Text(stringResource(if (original.acceptedExpenseId != null) R.string.manual_submission_done
                        else R.string.manual_submission_unknown))
                    original.acceptedExpenseId?.let { id ->
                        TextButton(onClick = { actions.onOpenExpense(id) }) { Text(stringResource(R.string.manual_submission_open)) }
                    }
                }
                else -> Text(stringResource(if (original.row.status == PendingMutationStatus.InFlight)
                    R.string.manual_submission_sending else R.string.manual_submission_waiting))
            }
        }
    }
}

@Composable
internal fun ManualCreationOriginalSummary(original: ManualExpenseCreationProjection) {
    val request = original.request
    if (request == null) {
        Text(stringResource(R.string.manual_submission_unknown))
        return
    }
    val currency = request.originalCurrency?.takeIf { it.isNotBlank() }
    val amount = request.originalAmount?.takeIf { it.isNotBlank() }
    Text(if (currency != null && amount != null) "$currency $amount" else stringResource(R.string.manual_submission_unknown),
        style = MaterialTheme.typography.titleLarge)
    request.merchant?.takeIf { it.isNotBlank() }?.let { Text(it) }
    (request.spentAt ?: request.expenseTime)?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
    request.homeCurrencyCode?.let { Text(stringResource(R.string.manual_submission_home, it), style = MaterialTheme.typography.bodySmall) }
}

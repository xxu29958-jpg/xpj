package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.viewmodel.DebtBillTaskAction
import com.ticketbox.viewmodel.DebtListUiState
import com.ticketbox.viewmodel.DebtListViewModel

/** Both Debt and Relations use this original-task consumer inside their shared form. */
@Composable
internal fun DebtBillInputPanel(state: DebtListUiState, model: DebtListViewModel, onPickOriginal: () -> Unit) {
    if (state.billInputs.isEmpty() && state.activeBillCaptureKey == null) return
    Column {
        Text(stringResource(R.string.debt_bill_originals), style = MaterialTheme.typography.titleSmall)
        if (state.activeBillCaptureKey != null && state.activeBill == null) {
            Text(stringResource(R.string.debt_bill_local_save_unverified), style = MaterialTheme.typography.bodySmall)
            TextButton(onClick = onPickOriginal, enabled = state.canModify && !state.isSubmitting && !state.isParsingBill) {
                Text(stringResource(R.string.debt_bill_retry_capture))
            }
        }
        state.billInputs.forEach { input ->
            DebtBillInputRow(input, state, model)
        }
    }
    state.billPreview?.let { DebtBillOriginalDialog(it, model::dismissFlash) }
}

@Composable
private fun DebtBillInputRow(input: com.ticketbox.data.repository.DebtBillInput, state: DebtListUiState, model: DebtListViewModel) {
    Text(input.payload.file.metadata.fileName)
    Text(stringResource(when {
        input.source?.parseOutcome?.status == "failed" -> R.string.debt_bill_suggestion_failed_kept
        input.source != null -> R.string.debt_bill_source_retained
        input.needsAttention -> R.string.debt_bill_capture_needs_attention
        else -> R.string.debt_bill_capture_waiting
    }), style = MaterialTheme.typography.bodySmall)
    TextButton(onClick = { model.billTask(input.captureKey, DebtBillTaskAction.Resume) }, enabled = !state.isSubmitting) {
        Text(stringResource(R.string.debt_bill_continue_original))
    }
    TextButton(onClick = { model.billTask(input.captureKey, DebtBillTaskAction.Preview) }) {
        Text(stringResource(R.string.debt_bill_view_original))
    }
    if (state.activeBillCaptureKey == input.captureKey && !state.publicationUnverified) {
        TextButton(onClick = { model.billTask(input.captureKey, if (input.source == null)
            DebtBillTaskAction.RetryCapture else DebtBillTaskAction.Parse) },
            enabled = state.canModify && !state.isSubmitting && !state.isParsingBill) {
            Text(stringResource(if (input.source == null) R.string.debt_bill_retry_capture else R.string.debt_bill_retry_suggestion))
        }
    }
}

@Composable
internal fun DebtBillOriginalDialog(bytes: ByteArray, onDismiss: () -> Unit) {
    val image = remember(bytes) { com.ticketbox.domain.model.ProtectedImage(bytes, null) }
    AlertDialog(onDismissRequest = onDismiss, title = { Text(stringResource(R.string.debt_bill_view_original)) },
        text = { com.ticketbox.ui.components.AppAsyncImage(image, Modifier.fillMaxWidth()) },
        confirmButton = { TextButton(onClick = onDismiss) { Text(stringResource(android.R.string.ok)) } })
}

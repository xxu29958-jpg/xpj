package com.ticketbox.ui.screens.expense.fact

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.viewmodel.ExpenseFactUiState
import com.ticketbox.viewmodel.ExpenseFactViewModel
import com.ticketbox.viewmodel.discardFactInput
import com.ticketbox.viewmodel.resumeFactInput
import com.ticketbox.viewmodel.retryFactInputSave

@Composable
internal fun FactInputContinuitySection(state: ExpenseFactUiState, viewModel: ExpenseFactViewModel) {
    FactInputSaveStatus(state, viewModel::retryFactInputSave)
    if (state.factInputKeys.isEmpty()) return
    var discard by remember { mutableStateOf<String?>(null) }
    Column {
        AppSectionHeader(title = stringResource(R.string.expense_fact_inputs_title))
        state.factInputKeys.sorted().forEach { key ->
            Row {
                TextButton(onClick = { viewModel.resumeFactInput(key) },
                    enabled = !state.readOnly && !state.factInputBusy && state.expense != null) {
                    Text(stringResource(R.string.expense_fact_input_resume, factInputLabel(key)))
                }
                TextButton(onClick = { discard = key }, enabled = !state.factInputBusy) {
                    Text(stringResource(R.string.expense_fact_input_discard))
                }
            }
        }
    }
    discard?.let { key ->
        AlertDialog(onDismissRequest = { discard = null }, title = { Text(factInputLabel(key)) },
            text = { Text(stringResource(R.string.expense_fact_input_discard_confirm)) },
            confirmButton = { TextButton(onClick = { viewModel.discardFactInput(key); discard = null }) {
                Text(stringResource(R.string.expense_fact_input_discard)) } },
            dismissButton = { TextButton(onClick = { discard = null }) { Text(stringResource(R.string.common_cancel)) } })
    }
}

@Composable
internal fun FactInputSaveStatus(state: ExpenseFactUiState, retry: () -> Unit) {
    state.factInputError?.let {
        AppStatusBanner(message = it, tone = MessageTone.Danger)
        TextButton(onClick = retry, enabled = !state.factInputBusy && !state.factInputWriting) {
            Text(stringResource(R.string.expense_fact_input_retry))
        }
    }
    if (state.factInputKeys.isNotEmpty() && state.factInputError == null) {
        Text(stringResource(if (state.factInputWriting) R.string.expense_fact_input_writing else R.string.expense_fact_input_saved),
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun factInputLabel(key: String) = stringResource(when (key) {
    "correction" -> R.string.expense_correction_sheet_title
    "refund" -> R.string.expense_offset_sheet_title_refund
    "reversal" -> R.string.expense_offset_sheet_title_reversal
    else -> R.string.expense_offset_void_title
})

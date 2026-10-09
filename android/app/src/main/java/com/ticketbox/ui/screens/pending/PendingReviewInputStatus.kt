package com.ticketbox.ui.screens.pending

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
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
import androidx.compose.ui.Modifier
import com.ticketbox.R
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.expenseTimeLabel
import com.ticketbox.ui.components.formatExpensePrimaryAmount
import com.ticketbox.viewmodel.PendingReviewTask

@Composable
internal fun PendingReviewInputStatus(state: PendingReviewSheetHostState, actions: PendingReviewSheetHostActions) {
    var discard by remember { mutableStateOf(false) }
    Column {
        if (!state.inputReady) Text(stringResource(R.string.pending_review_input_loading))
        state.inputError?.let {
            Text(it, color = MaterialTheme.colorScheme.error)
            TextButton(onClick = actions.onRetryReviewInput) { Text(stringResource(R.string.expense_fact_input_retry)) }
        }
        if (state.inputNeedsReview) Text(stringResource(R.string.expense_fact_input_review_required))
        if (state.inputSaved || state.inputWriting) {
            Text(stringResource(if (state.inputWriting) R.string.expense_fact_input_writing else R.string.expense_fact_input_saved),
                style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            if (!state.readOnly) TextButton(onClick = actions.onReviewCurrentBasis, enabled = state.inputReady && !state.inputWriting) {
                Text(stringResource(R.string.pending_review_input_review_current))
            }
            TextButton(onClick = { discard = true }, enabled = state.inputReady && !state.inputWriting) {
                Text(stringResource(R.string.expense_fact_input_discard))
            }
        }
    }
    if (discard) AlertDialog(onDismissRequest = { discard = false },
        text = { Text(stringResource(R.string.expense_fact_input_discard_confirm)) },
        confirmButton = { TextButton(onClick = { discard = false; actions.onDiscardReviewInput() }) {
            Text(stringResource(R.string.expense_fact_input_discard)) } },
        dismissButton = { TextButton(onClick = { discard = false }) { Text(stringResource(R.string.common_cancel)) } })
}

@Composable
internal fun PendingReviewTasks(tasks: List<PendingReviewTask>, error: String?, retry: () -> Unit, resume: (PendingReviewTask) -> Unit) {
    Column {
        AppSectionHeader(title = stringResource(R.string.expense_fact_inputs_title))
        error?.let {
            Text(it, color = MaterialTheme.colorScheme.error)
            TextButton(onClick = retry) { Text(stringResource(R.string.expense_fact_input_retry)) }
        }
        tasks.forEach { task ->
            TextButton(onClick = { resume(task) }) {
                Column(Modifier.fillMaxWidth()) {
                    val expense = task.expense
                    val merchant = expense.merchant?.takeIf(String::isNotBlank)
                        ?: stringResource(R.string.pending_duplicate_sheet_merchant_missing)
                    Text(stringResource(R.string.pending_review_input_resume, reviewInputLabel(task.original.formKey), merchant))
                    val currency = if (expense.originalAmountMinor != null)
                        expense.originalCurrencyCodeRaw ?: expense.originalCurrencyCode.storageKey
                    else expense.homeCurrencyCode ?: expense.homeCurrency.storageKey
                    Text(stringResource(R.string.pending_review_input_summary, formatExpensePrimaryAmount(expense), currency,
                        expenseTimeLabel(expense).asString()), style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

@Composable
private fun reviewInputLabel(key: String) = stringResource(when (key) {
    "pending_category" -> R.string.quick_category_sheet_title
    "pending_merchant" -> R.string.pending_quick_merchant_title
    "pending_amount" -> R.string.pending_missing_amount_title
    else -> R.string.pending_row_action_duplicate
})

package com.ticketbox.ui.screens.expense

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.MaterialTheme
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
import com.ticketbox.domain.model.BackgroundTask
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.pendingNeedsFx
import com.ticketbox.ui.asString
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.ExpenseEditPrimaryActions
import com.ticketbox.viewmodel.ExpenseEditUiState

@StringRes
internal fun expenseFxTaskStatusRes(task: BackgroundTask?): Int = when (task?.status) {
    "queued" -> R.string.expense_fx_queued
    "running" -> R.string.expense_fx_running
    "completed" -> R.string.expense_fx_completed
    "failed", "cancelled" -> R.string.expense_fx_failed
    else -> R.string.expense_fx_waiting
}

@Composable
internal fun ExpenseFxStatusCard(
    expense: Expense,
    editState: ExpenseEditUiState,
    hasDraftChanges: Boolean,
    actions: ExpenseEditPrimaryActions,
) {
    val state = editState.fx
    if (expense.status != "pending" || (!pendingNeedsFx(expense) && state.task == null)) return
    val busy = editState.saving || editState.expenseLoading
    val actionsEnabled = !busy && !state.loading
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Text(stringResource(expenseFxTaskStatusRes(state.task)), style = MaterialTheme.typography.titleSmall)
        Text(stringResource(R.string.expense_fx_manual_recovery), style = MaterialTheme.typography.bodySmall)
        state.message?.let { Text(it.asString(), color = MaterialTheme.colorScheme.error) }
        TextButton(onClick = actions.onRefreshFx, enabled = actionsEnabled) {
            Text(stringResource(R.string.expense_fx_refresh))
        }
        if (pendingNeedsFx(expense) && !editState.readOnly && (state.task == null || state.task.status in setOf("failed", "cancelled"))) {
            TextButton(onClick = actions.onRetryFx, enabled = actionsEnabled) { Text(stringResource(R.string.expense_fx_retry)) }
        }
        ExpenseFxReviewAction(actionsEnabled, hasDraftChanges) { actions.onLoadFxReview(false) }
    }
}

/** Raw form replacement is a user's explicit choice; stale OCC must not force a save first. */
@Composable
private fun ExpenseFxReviewAction(enabled: Boolean, hasDraftChanges: Boolean, loadReview: () -> Unit) {
    var confirmReplacement by remember { mutableStateOf(false) }
    TextButton(onClick = { if (hasDraftChanges) confirmReplacement = true else loadReview() }, enabled = enabled) {
        Text(stringResource(R.string.expense_fx_load_review))
    }
    if (confirmReplacement) AlertDialog(
        onDismissRequest = { confirmReplacement = false },
        title = { Text(stringResource(R.string.expense_fx_load_review)) },
        text = { Text(stringResource(R.string.expense_fx_replace_draft_explanation)) },
        confirmButton = { TextButton(onClick = { confirmReplacement = false; loadReview() }, enabled = enabled) {
            Text(stringResource(R.string.expense_fx_replace_draft))
        } },
        dismissButton = { TextButton(onClick = { confirmReplacement = false }) {
            Text(stringResource(R.string.expense_fx_keep_draft))
        } },
    )
}

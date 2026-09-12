package com.ticketbox.ui.screens.expense

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.BackgroundTask
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.FxContract
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
    if (expense.status != "pending" || (expense.fxStatus != FxContract.StatusPending && state.task == null)) return
    val busy = editState.saving || editState.expenseLoading
    val actionsEnabled = !busy && !state.loading
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
        Text(stringResource(expenseFxTaskStatusRes(state.task)), style = MaterialTheme.typography.titleSmall)
        Text(stringResource(R.string.expense_fx_manual_recovery), style = MaterialTheme.typography.bodySmall)
        state.message?.let { Text(it.asString(), color = MaterialTheme.colorScheme.error) }
        TextButton(onClick = actions.onRefreshFx, enabled = actionsEnabled) {
            Text(stringResource(R.string.expense_fx_refresh))
        }
        if (!editState.readOnly && (state.task == null || state.task.status in setOf("failed", "cancelled"))) {
            TextButton(onClick = actions.onRetryFx, enabled = actionsEnabled) { Text(stringResource(R.string.expense_fx_retry)) }
        }
        if (state.task?.status == "completed") {
            if (hasDraftChanges) Text(stringResource(R.string.expense_fx_save_draft_first), style = MaterialTheme.typography.bodySmall)
            TextButton(onClick = { actions.onLoadFxReview(hasDraftChanges) }, enabled = actionsEnabled && !hasDraftChanges) {
                Text(stringResource(R.string.expense_fx_load_review))
            }
        }
    }
}

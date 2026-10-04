package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.RestartAlt
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.PendingExpenseCorrection
import com.ticketbox.ui.components.AppOutlinedButton
import com.ticketbox.ui.components.AppOutlinedButtonOptions
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.expense.fact.CorrectionSubmissionActions
import com.ticketbox.ui.screens.expense.fact.CorrectionSubmissionOptions
import com.ticketbox.ui.screens.expense.fact.ExpenseCorrectionSubmissionCard
import com.ticketbox.viewmodel.OutboxStatusUiState

/** Original-command recovery stays ahead of read-only refresh and identity quarantine. */
@Composable
internal fun SyncStatusExpenseReviewSection(state: OutboxStatusUiState, actions: SyncStatusActions) {
    (state.status.conflicts + state.status.failed).filter { it.type == PendingMutationType.OriginalAttachment }.forEach { row ->
        val id = row.targetId.removePrefix("expense:").toLongOrNull()
        Text(stringResource(R.string.original_attention))
        if (id != null) TextButton(onClick = { actions.onOpenExpense(id) }) { Text(stringResource(R.string.original_open_bill)) }
    }
    state.correctionObservation.corrections.filter { !it.delivered }.forEach { pending ->
        SyncStatusCorrectionRow(pending, state, actions)
    }
}

@Composable
internal fun SyncStatusExpenseRefreshSection(state: OutboxStatusUiState, actions: SyncStatusActions) {
    val corrections = state.correctionObservation.corrections.filter { it.refreshRequired }
    val rows = state.status.refreshRequired.filter { it.type != PendingMutationType.CorrectExpense }.distinctBy { it.targetId }
    if (corrections.isEmpty() && rows.isEmpty()) return
    SettingsSection(title = stringResource(R.string.sync_status_refresh_title), icon = Icons.Filled.RestartAlt) {
        corrections.forEach { pending -> SyncStatusCorrectionRow(pending, state, actions) }
        rows.forEach { row -> SyncStatusAcceptedRow(row, state, actions) }
    }
}

@Composable
private fun SyncStatusCorrectionRow(pending: PendingExpenseCorrection, state: OutboxStatusUiState, actions: SyncStatusActions) {
    ExpenseCorrectionSubmissionCard(
        pending = pending,
        options = CorrectionSubmissionOptions(state.correctionObservation.access?.canModify == true, state.busyRowId != null, false),
        actions = CorrectionSubmissionActions(
            recover = { drop -> if (drop) actions.onDropFailed(pending.row) else actions.onRetry(pending.row) },
            reviewFact = pending.expenseId?.let { id -> { actions.onOpenExpense(id) } },
            repairRate = state.correctionObservation.access?.binding?.let { binding ->
                { gap -> actions.onRepairCorrectionRate(binding, gap) }
            }),
    )
}

@Composable
private fun SyncStatusAcceptedRow(row: OutboxRow, state: OutboxStatusUiState, actions: SyncStatusActions) {
    val budget = state.budgetSaves[row.id]
    SettingsOpenPanel(verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        Text(stringResource(syncStatusMutationLabelResources.getValue(row.type)), style = MaterialTheme.typography.titleSmall)
        Text(stringResource(if (budget != null) R.string.budget_saved_read_pending else R.string.sync_status_refresh_required),
            style = MaterialTheme.typography.bodyMedium)
        budget?.let { com.ticketbox.ui.screens.budget.BudgetSaveIntentSummary(it) }
        AppOutlinedButton(onClick = { actions.onRefreshAcceptedResult(row) },
            options = AppOutlinedButtonOptions(enabled = state.busyRowId == null)) {
            Text(stringResource(if (budget != null) R.string.budget_read_recover else R.string.sync_status_refresh_expense))
        }
        budget?.intent?.takeIf { budget.hasSupportedIntent }?.let { intent ->
            TextButton(onClick = { actions.onOpenBudget(intent.month) }) {
                Text(stringResource(R.string.budget_save_open_month))
            }
        }
    }
}

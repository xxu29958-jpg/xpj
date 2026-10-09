package com.ticketbox.ui.screens.pending.sheets

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppAdaptiveMetricGrid
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSheetActionFeedback
import com.ticketbox.ui.components.AppSheetActionFeedbackState
import com.ticketbox.ui.components.duplicateNoticeBody
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.pending.PendingReviewSheetHostActions
import com.ticketbox.ui.screens.pending.PendingReviewSheetHostState
import com.ticketbox.viewmodel.PendingSheet

@Composable
internal fun DuplicateConfirmSheetContent(
    sheet: PendingSheet.Duplicate,
    state: PendingReviewSheetHostState,
    actions: PendingReviewSheetHostActions,
) {
    val expense = sheet.expense
    val busy = expense.id in state.actionInProgressIds || !state.inputReady || state.inputNeedsReview
    ReviewSheetScaffold(
        title = stringResource(R.string.pending_duplicate_sheet_title),
        subtitle = stringResource(R.string.pending_duplicate_sheet_hint),
        actions = {
            DuplicateDecisionActions(sheet, state, actions, busy)
        },
    ) {
        AppAdaptiveMetricGrid(itemCount = 2) { index, modifier ->
            Column(modifier = modifier, verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                if (index == 0) DuplicateReference(sheet, actions)
                else {
                    Text(stringResource(R.string.pending_duplicate_current), style = MaterialTheme.typography.titleMedium)
                    Text(stringResource(R.string.expense_edit_status_pending), style = MaterialTheme.typography.labelMedium)
                    ReviewExpenseSummary(expense, state.thumbnails[expense.id]) { actions.onOpenExpense(expense.id) }
                }
            }
        }
        expense.duplicateReason?.takeIf(String::isNotBlank)?.let {
            Text(duplicateNoticeBody(it), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (!state.readOnly) Row(verticalAlignment = Alignment.CenterVertically) {
            Checkbox(checked = sheet.keepBothConfirmed, onCheckedChange = actions.onDuplicateDecisionChange,
                enabled = !busy && !sheet.referenceLoading)
            Text(stringResource(if (sheet.reference != null) R.string.pending_duplicate_different else R.string.pending_duplicate_keep_current_check),
                modifier = Modifier.weight(1f))
        }
        sheet.reference?.let { reference ->
            TextButton(onClick = { actions.onCompareOriginals(listOf(reference.id, expense.id)) }, enabled = !busy) {
                Text(stringResource(R.string.pending_duplicate_originals))
            }
        }
        com.ticketbox.ui.screens.pending.PendingReviewInputStatus(state, actions)
    }
}

@Composable
private fun DuplicateReference(sheet: PendingSheet.Duplicate, actions: PendingReviewSheetHostActions) {
    Text(stringResource(R.string.pending_duplicate_reference), style = MaterialTheme.typography.titleMedium)
    sheet.reference?.let { reference ->
        Text(when (reference.status) {
            "confirmed" -> stringResource(R.string.expense_edit_status_confirmed)
            "pending" -> stringResource(R.string.expense_edit_status_pending)
            "rejected" -> stringResource(R.string.pending_duplicate_reference_ignored)
            else -> reference.status
        }, style = MaterialTheme.typography.labelMedium)
        ReviewExpenseSummary(reference, sheet.referenceThumbnail) { actions.onOpenExpense(reference.id) }
    }
    if (sheet.referenceLoading) Text(stringResource(R.string.pending_duplicate_reference_loading))
    sheet.referenceMessage?.let {
        Text(it.asString(), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (sheet.expense.duplicateOfId != null) TextButton(onClick = actions.onRetryDuplicateReference, enabled = !sheet.referenceLoading) {
            Text(stringResource(R.string.common_retry))
        }
    }
}

@Composable
private fun DuplicateDecisionActions(sheet: PendingSheet.Duplicate, state: PendingReviewSheetHostState,
    actions: PendingReviewSheetHostActions, busy: Boolean) {
    val expense = sheet.expense
    if (state.readOnly) Text(stringResource(R.string.common_readonly_ledger))
    else AppSheetActionFeedback(
        primary = AppSheetAction(
            text = stringResource(when {
                busy -> R.string.pending_duplicate_sheet_processing
                sheet.reference != null -> R.string.pending_duplicate_sheet_keep_both
                else -> R.string.pending_duplicate_keep_current
            }),
            enabled = !busy && sheet.keepBothConfirmed && !sheet.referenceLoading,
            onClick = { actions.onKeepBoth(expense) },
        ),
        state = AppSheetActionFeedbackState(statusMessage = state.statusMessage),
    )
    if (!state.readOnly) TextButton(onClick = { actions.onIgnoreCurrent(expense) }, enabled = !busy,
        modifier = Modifier.fillMaxWidth()) { Text(stringResource(R.string.pending_duplicate_sheet_ignore_current)) }
}

package com.ticketbox.ui.screens.plan

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Column
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
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.PendingGoalEdit
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.viewmodel.SpendingGoalDetailUiState
import com.ticketbox.viewmodel.SpendingGoalDetailViewModel

@Composable
internal fun SpendingGoalSubmissionStatus(state: SpendingGoalDetailUiState, viewModel: SpendingGoalDetailViewModel) {
    var stopping by remember(state.publicId) { mutableStateOf<PendingGoalEdit?>(null) }
    val active = state.pendingEdits.filter { !it.isDone }
    val shown = active.ifEmpty { listOfNotNull(state.pendingEdits.maxByOrNull { it.row.id }) }
    shown.forEach { pending ->
        AppContentCard {
            val text = pending.submissionText()
            AppStatusBanner(text, if (pending.isDone && pending.confirmed != null) MessageTone.Success else MessageTone.Info)
            val accepted = pending.confirmed
            if (accepted != null) SpendingGoalOriginalSummary(accepted.name, accepted.month,
                accepted.targetAmountCents, accepted.homeCurrencyCode)
            else pending.request?.let { request ->
                SpendingGoalOriginalSummary(request.name, request.month, request.targetAmountCents, request.homeCurrencyCode)
            }
            Row {
                if (pending.canRetry && state.canModify) TextButton(enabled = !state.isSaving,
                    onClick = { viewModel.recover(pending, drop = false) }) { Text(stringResource(R.string.spending_goal_submission_retry)) }
                if (pending.canDrop) TextButton(enabled = !state.isSaving,
                    onClick = { stopping = pending }) { Text(stringResource(R.string.spending_goal_submission_drop)) }
            }
        }
    }
    stopping?.takeIf { selected -> state.pendingEdits.any { it.row == selected.row } }?.let { original ->
        StopGoalEditDialog(original, onDismiss = { stopping = null }, onConfirm = {
            stopping = null
            viewModel.recover(original, drop = true)
        })
    }
}

@Composable
private fun StopGoalEditDialog(original: PendingGoalEdit, onDismiss: () -> Unit, onConfirm: () -> Unit) {
    AlertDialog(onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.spending_goal_submission_drop)) },
        text = { Column {
            Text(stringResource(R.string.goal_submission_stop_body))
            original.request?.let { SpendingGoalOriginalSummary(it.name, it.month, it.targetAmountCents, it.homeCurrencyCode) }
        } },
        confirmButton = { TextButton(onClick = onConfirm) { Text(stringResource(R.string.spending_goal_submission_drop)) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.common_cancel)) } },
    )
}

private fun com.ticketbox.data.repository.PendingGoalEdit.submissionText(): UiText = UiText.res(when (row.status) {
    PendingMutationStatus.Pending -> R.string.spending_goal_submission_pending
    PendingMutationStatus.InFlight -> R.string.spending_goal_submission_in_flight
    PendingMutationStatus.Conflict -> R.string.spending_goal_submission_conflict
    PendingMutationStatus.Failed -> if (canRetry) R.string.spending_goal_submission_uncertain
        else R.string.spending_goal_submission_failed
    PendingMutationStatus.Done -> if (confirmed != null) R.string.spending_goal_submission_done
        else R.string.spending_goal_submission_attention
    else -> R.string.spending_goal_submission_attention
})

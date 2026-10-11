package com.ticketbox.ui.screens.plan

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
import com.ticketbox.ui.components.AppAction
import com.ticketbox.ui.components.AppActionRow
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.viewmodel.SpendingGoalDetailUiState
import com.ticketbox.viewmodel.SpendingGoalDetailViewModel

@Composable
internal fun SpendingGoalSubmissionStatus(state: SpendingGoalDetailUiState, viewModel: SpendingGoalDetailViewModel) {
    val active = state.pendingEdits.filter { !it.isDone }
    val shown = active.ifEmpty { listOfNotNull(state.pendingEdits.maxByOrNull { it.row.id }) }
    shown.forEach { pending ->
        GoalEditSubmissionStatus(pending, state.isSaving, state.canModify, viewModel::recover)
    }
}

@Composable
internal fun GoalEditSubmissionStatus(pending: PendingGoalEdit, busy: Boolean, canModify: Boolean,
    onRecover: (PendingGoalEdit, Boolean) -> Unit) {
    var stopping by remember(pending.row) { mutableStateOf(false) }
        AppContentCard {
            val text = pending.submissionText()
            AppStatusBanner(text, if (pending.isDone && pending.confirmed != null) MessageTone.Success else MessageTone.Info)
            GoalEditIntentSummary(pending)
            val retry = if (pending.canRetry && canModify) AppAction(
                stringResource(R.string.spending_goal_submission_retry), enabled = !busy,
                onClick = { onRecover(pending, false) }) else null
            val stop = if (pending.canDrop) AppAction(stringResource(pending.stopLabel), enabled = !busy,
                onClick = { stopping = true }) else null
            (retry ?: stop)?.let { primary ->
                AppActionRow(primary = primary, secondary = stop.takeIf { retry != null })
            }
        }
    if (stopping) {
        StopGoalEditDialog(pending, onDismiss = { stopping = false }, onConfirm = {
            stopping = false
            onRecover(pending, true)
        })
    }
}

@Composable
private fun StopGoalEditDialog(original: PendingGoalEdit, onDismiss: () -> Unit, onConfirm: () -> Unit) {
    AlertDialog(onDismissRequest = onDismiss,
        title = { Text(stringResource(original.stopLabel)) },
        text = { Column {
            Text(stringResource(if (original.stopLabel == R.string.debt_goal_links_review) R.string.debt_goal_links_review_body
                else R.string.goal_submission_stop_body))
            GoalEditIntentSummary(original)
        } },
        confirmButton = { TextButton(onClick = onConfirm) { Text(stringResource(original.stopLabel)) } },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.common_cancel)) } },
    )
}

private val PendingGoalEdit.stopLabel: Int get() = if (canReviewDebtEdit)
    R.string.debt_goal_links_review else R.string.spending_goal_submission_drop

@Composable
internal fun GoalEditIntentSummary(original: PendingGoalEdit) {
    val links = original.debtEdit
    val accepted = original.confirmed
    if (links != null) {
        Text(links.goalName)
        val fallbackLabel = stringResource(R.string.debt_goal_links_unavailable)
        links.request?.let { request ->
            Text(request.debtPublicIds.joinToString("、") { links.selectedLabels[it].orEmpty().ifBlank { fallbackLabel } })
        }
        links.dateRequest?.let { request ->
            Text(request.targetDate ?: stringResource(R.string.debt_goal_date_cleared))
        }
    } else if (accepted != null) SpendingGoalOriginalSummary(accepted.name, accepted.month,
        accepted.targetAmountCents, accepted.homeCurrencyCode)
    else original.request?.let { request ->
        SpendingGoalOriginalSummary(request.name, request.month, request.targetAmountCents, request.homeCurrencyCode)
    }
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

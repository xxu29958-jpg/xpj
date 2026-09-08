package com.ticketbox.ui.screens.plan

import androidx.compose.foundation.layout.Row
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.viewmodel.SpendingGoalDetailUiState
import com.ticketbox.viewmodel.SpendingGoalDetailViewModel

@Composable
internal fun SpendingGoalSubmissionStatus(state: SpendingGoalDetailUiState, viewModel: SpendingGoalDetailViewModel) {
    val active = state.pendingEdits.filter { !it.isDone }
    val shown = active.ifEmpty { listOfNotNull(state.pendingEdits.maxByOrNull { it.row.id }) }
    shown.forEach { pending ->
        AppContentCard {
            val text = pending.submissionText()
            AppStatusBanner(text, if (pending.isDone) MessageTone.Success else MessageTone.Info)
            pending.request?.let { request ->
                request.name?.let { Text(it) }
                request.targetAmountCents?.let { amount ->
                    Text(stringResource(R.string.spending_goal_submission_amount, formatDisplayAmount(amount,
                        CurrencyDisplay.forRecord(state.ledgerCurrency?.storageKey ?: stringResource(R.string.spending_goal_currency_unknown)))))
                }
                request.month?.let { Text(stringResource(R.string.spending_goal_submission_month, it)) }
            }
            Row {
                if (pending.canRetry && state.canModify) TextButton(enabled = !state.isSaving,
                    onClick = { viewModel.recover(pending, drop = false) }) { Text(stringResource(R.string.spending_goal_submission_retry)) }
                if (pending.canDrop) TextButton(enabled = !state.isSaving,
                    onClick = { viewModel.recover(pending, drop = true) }) { Text(stringResource(R.string.spending_goal_submission_drop)) }
            }
        }
    }
}

private fun com.ticketbox.data.repository.PendingGoalEdit.submissionText(): UiText = UiText.res(when (row.status) {
    PendingMutationStatus.Pending -> R.string.spending_goal_submission_pending
    PendingMutationStatus.InFlight -> R.string.spending_goal_submission_in_flight
    PendingMutationStatus.Conflict -> R.string.spending_goal_submission_conflict
    PendingMutationStatus.Failed -> if (canRetry) R.string.spending_goal_submission_uncertain
        else R.string.spending_goal_submission_failed
    PendingMutationStatus.Done -> R.string.spending_goal_submission_done
    else -> R.string.spending_goal_submission_attention
})

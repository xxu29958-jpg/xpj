package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Row
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
import com.ticketbox.data.repository.PendingGoalCreation
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.AppStatusBanner

@Composable
fun GoalCreationIntentSummary(pending: PendingGoalCreation) {
    val request = pending.request
    if (request == null) Text(stringResource(R.string.goal_creation_unreadable)) else {
        com.ticketbox.ui.screens.plan.SpendingGoalOriginalSummary(request.name, request.month,
            request.targetAmountCents, request.homeCurrencyCode)
        request.category?.let { Text(it) }
    }
}

@Composable
internal fun GoalCreationSubmissionStatus(pending: PendingGoalCreation, busy: Boolean, canModify: Boolean,
    onRecover: (PendingGoalCreation, Boolean) -> Unit) {
    var stopping by remember(pending.row.ownerKey, pending.row.ledgerId, pending.row.serverUrl) {
        mutableStateOf<PendingGoalCreation?>(null)
    }
    stopping?.takeIf { it.row == pending.row }?.let { original ->
        AlertDialog(onDismissRequest = { stopping = null }, title = { Text(stringResource(R.string.goal_creation_drop)) },
            text = { androidx.compose.foundation.layout.Column {
                GoalCreationIntentSummary(original)
                Text(stringResource(R.string.goal_submission_stop_body))
            } }, confirmButton = { TextButton(enabled = !busy, onClick = { stopping = null; onRecover(original, true) }) {
                Text(stringResource(R.string.goal_creation_drop))
            } }, dismissButton = { TextButton(onClick = { stopping = null }) { Text(stringResource(R.string.common_cancel)) } })
    }
    AppContentCard {
        AppStatusBanner(UiText.res(when {
            pending.canRetry -> R.string.goal_creation_uncertain
            pending.canDrop -> R.string.goal_creation_failed
            else -> R.string.goal_creation_pending
        }), MessageTone.Info)
        GoalCreationIntentSummary(pending)
        Row {
            if (pending.canRetry && canModify) TextButton(enabled = !busy, onClick = { onRecover(pending, false) }) {
                Text(stringResource(R.string.spending_goal_submission_retry))
            }
            if (pending.canDrop) TextButton(enabled = !busy, onClick = { stopping = pending }) {
                Text(stringResource(R.string.goal_creation_drop))
            }
        }
    }
}

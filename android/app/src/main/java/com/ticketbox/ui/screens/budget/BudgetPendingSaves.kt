package com.ticketbox.ui.screens.budget

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.PendingBudgetSave
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.settings.friendlyLastError
import com.ticketbox.ui.screens.settings.isExpiredFailure

@Composable
internal fun BudgetPendingSaves(saves: List<PendingBudgetSave>, recover: (PendingBudgetSave, Boolean) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        saves.forEach { pending -> BudgetSaveStatus(pending, recover) }
    }
}

@Composable
private fun BudgetSaveStatus(pending: PendingBudgetSave, recover: (PendingBudgetSave, Boolean) -> Unit) {
    var confirmDrop by rememberSaveable(pending.row.id) { mutableStateOf(false) }
    HorizontalDivider()
    Text(stringResource(when (pending.row.status) {
        PendingMutationStatus.Done -> R.string.budget_message_saved
        PendingMutationStatus.Pending, PendingMutationStatus.InFlight -> R.string.budget_message_queued
        else -> R.string.budget_save_attention
    }))
    pending.intent?.let { intent ->
        Text(intent.month + " · " + formatDisplayAmount(intent.request.totalAmountCents,
            CurrencyDisplay.forRecord(intent.request.homeCurrencyCode)))
    }
    if (pending.row.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict)) {
        Text(friendlyLastError(pending.row.lastError, stringResource(R.string.budget_save_attention)))
        if (pending.row.status == PendingMutationStatus.Failed && !isExpiredFailure(pending.row.lastError)) {
            TextButton(onClick = { recover(pending, false) }, enabled = pending.intent != null) {
                Text(stringResource(R.string.sync_status_failed_button_retry))
            }
        }
        TextButton(onClick = { confirmDrop = true }) { Text(stringResource(R.string.budget_save_drop)) }
    }
    if (confirmDrop) AlertDialog(onDismissRequest = { confirmDrop = false },
        title = { Text(stringResource(R.string.budget_save_drop)) },
        text = { Text(stringResource(R.string.budget_save_drop_explanation)) },
        confirmButton = { TextButton(onClick = { confirmDrop = false; recover(pending, true) }) {
            Text(stringResource(R.string.budget_save_drop))
        } },
        dismissButton = { TextButton(onClick = { confirmDrop = false }) { Text(stringResource(R.string.common_cancel)) } })
}

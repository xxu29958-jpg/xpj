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

@Composable
internal fun BudgetPendingSaves(saves: List<PendingBudgetSave>, canModify: Boolean, recover: (PendingBudgetSave, Boolean) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        saves.forEach { pending -> BudgetSaveStatus(pending, canModify, recover) }
    }
}

@Composable
private fun BudgetSaveStatus(pending: PendingBudgetSave, canModify: Boolean, recover: (PendingBudgetSave, Boolean) -> Unit) {
    var confirmDrop by rememberSaveable(pending.row.id) { mutableStateOf(false) }
    HorizontalDivider()
    Text(stringResource(when (pending.row.status) {
        PendingMutationStatus.Done -> R.string.budget_message_saved
        PendingMutationStatus.Pending, PendingMutationStatus.InFlight -> R.string.budget_message_queued
        else -> R.string.budget_save_attention
    }))
    BudgetSaveIntentSummary(pending)
    if (pending.row.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict)) {
        Text(friendlyLastError(pending.row.lastError, stringResource(R.string.budget_save_attention)))
        if (pending.canRetry && canModify) {
            TextButton(onClick = { recover(pending, false) }) {
                Text(stringResource(R.string.sync_status_failed_button_retry))
            }
        }
        TextButton(onClick = { confirmDrop = true }) { Text(stringResource(R.string.budget_save_drop)) }
    }
    if (confirmDrop) AlertDialog(onDismissRequest = { confirmDrop = false },
        title = { Text(stringResource(R.string.budget_save_drop)) },
        text = { Column { BudgetSaveIntentSummary(pending); Text(stringResource(R.string.budget_save_drop_explanation)) } },
        confirmButton = { TextButton(onClick = { confirmDrop = false; recover(pending, true) }) {
            Text(stringResource(R.string.budget_save_drop))
        } },
        dismissButton = { TextButton(onClick = { confirmDrop = false }) { Text(stringResource(R.string.common_cancel)) } })
}

/** Both sync entrances show the original monetary basis, never the current display default. */
@Composable
internal fun BudgetSaveIntentSummary(pending: PendingBudgetSave) {
    val intent = pending.intent?.takeIf { pending.hasSupportedIntent }
    if (intent == null) {
        Text(stringResource(R.string.budget_save_unsupported))
        return
    }
    val request = intent.request
    val currency = CurrencyDisplay.forRecord(request.homeCurrencyCode)
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        Text(intent.month + " · " + request.homeCurrencyCode)
        Text(stringResource(R.string.budget_editor_total_label) + " · " + formatDisplayAmount(request.totalAmountCents, currency))
        listOf(R.string.budget_editor_rollover_label to request.rolloverAmountCents,
            R.string.budget_editor_non_monthly_label to request.nonMonthlyAmountCents).filter { it.second != 0L }.forEach { (label, amount) ->
            Text(stringResource(label) + " · " + formatDisplayAmount(amount, currency))
        }
        request.categoryBudgets.forEach { Text(it.category + " · " + formatDisplayAmount(it.amountCents, currency)) }
        if (request.excludedCategories.isNotEmpty()) {
            Text(stringResource(R.string.budget_editor_excluded_label) + " · " + request.excludedCategories.joinToString("、"))
        }
    }
}

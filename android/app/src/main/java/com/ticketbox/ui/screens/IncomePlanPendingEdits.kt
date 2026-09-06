package com.ticketbox.ui.screens

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
import com.ticketbox.data.repository.PendingIncomePlanEdit
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.settings.isExpiredFailure

@Composable
internal fun IncomePlanIntentSummary(pending: PendingIncomePlanEdit) {
    val intent = pending.intent
    if (intent == null) {
        Text(stringResource(R.string.income_plan_edit_unsupported))
        return
    }
    Text(intent.originalLabel + " · " + intent.request.intentMonth)
    Text((intent.request.label ?: intent.originalLabel) + " · " +
        formatDisplayAmount(intent.request.amountCents ?: intent.originalAmountCents,
            CurrencyDisplay.forRecord(intent.homeCurrencyCode)))
    intent.request.incomeMonth?.let { Text(stringResource(R.string.income_plan_edit_target_month, it)) }
}

/** Displayed independently of the management GET; a saved edit remains recoverable offline. */
@Composable
internal fun IncomePlanPendingEdits(edits: List<PendingIncomePlanEdit>, recover: (PendingIncomePlanEdit, Boolean) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        edits.forEach { pending -> IncomePlanPendingEdit(pending, recover) }
    }
}

@Composable
private fun IncomePlanPendingEdit(pending: PendingIncomePlanEdit, recover: (PendingIncomePlanEdit, Boolean) -> Unit) {
    var confirmDrop by rememberSaveable(pending.row.id) { mutableStateOf(false) }
    HorizontalDivider()
    Text(stringResource(if (pending.row.status in setOf(PendingMutationStatus.Pending, PendingMutationStatus.InFlight))
        R.string.income_plan_edit_waiting else R.string.income_plan_edit_attention))
    IncomePlanIntentSummary(pending)
    if (pending.row.status == PendingMutationStatus.Conflict) Text(stringResource(R.string.income_plan_edit_conflict))
    val expired = isExpiredFailure(pending.row.lastError)
    if (expired) Text(stringResource(R.string.income_plan_edit_expired))
    if (pending.row.status == PendingMutationStatus.Failed && !expired) {
        TextButton(onClick = { recover(pending, false) }, enabled = pending.hasSupportedIntent) {
            Text(stringResource(R.string.income_plan_edit_retry))
        }
    }
    if (pending.row.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict)) {
        TextButton(onClick = { confirmDrop = true }) { Text(stringResource(R.string.income_plan_edit_drop)) }
    }
    if (confirmDrop) AlertDialog(onDismissRequest = { confirmDrop = false },
        title = { Text(stringResource(R.string.income_plan_edit_drop)) },
        text = { Text(stringResource(R.string.income_plan_edit_drop_explanation)) },
        confirmButton = { TextButton(onClick = { confirmDrop = false; recover(pending, true) }) {
            Text(stringResource(R.string.income_plan_edit_drop))
        } },
        dismissButton = { TextButton(onClick = { confirmDrop = false }) { Text(stringResource(R.string.common_cancel)) } })
}

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
import com.ticketbox.data.repository.PendingDebtAdjustment
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.settings.isExpiredFailure

@Composable
internal fun DebtAdjustmentIntentSummary(pending: PendingDebtAdjustment) {
    if (pending.row.status == PendingMutationStatus.Abandoned) Text(stringResource(R.string.debt_adjustment_stopped_body))
    val intent = pending.intent
    if (intent == null) {
        Text(stringResource(if (pending.row.status == PendingMutationStatus.Abandoned) {
            R.string.debt_adjustment_stopped_unreadable
        } else R.string.debt_adjustment_unsupported))
        return
    }
    Text(intent.subject.label ?: stringResource(R.string.debt_detail_title))
    Text(stringResource(R.string.debt_adjustment_original_amount,
        formatDisplayAmount(intent.request.amountCents, CurrencyDisplay.forRecord(intent.subject.homeCurrencyCode))))
    Text(intent.request.reason)
    if (pending.reductionRejected) Text(stringResource(R.string.debt_adjustment_reduction_rejected))
}

/** Original commands remain readable even when the canonical detail cannot be fetched. */
@Composable
internal fun DebtPendingAdjustments(pending: List<PendingDebtAdjustment>, recover: (PendingDebtAdjustment, Boolean) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        pending.forEach { row -> DebtPendingAdjustment(row, recover) }
    }
}

@Composable
private fun DebtPendingAdjustment(pending: PendingDebtAdjustment, recover: (PendingDebtAdjustment, Boolean) -> Unit) {
    var confirmDrop by rememberSaveable(pending.row.id) { mutableStateOf(false) }
    val status = pending.row.status
    val needsAttention = status in setOf(PendingMutationStatus.Conflict, PendingMutationStatus.Failed)
    HorizontalDivider()
    Text(stringResource(when {
        status == PendingMutationStatus.Abandoned -> R.string.debt_adjustment_stopped
        needsAttention -> R.string.debt_adjustment_attention
        else -> R.string.debt_adjustment_waiting
    }))
    DebtAdjustmentIntentSummary(pending)
    val expired = isExpiredFailure(pending.row.lastError)
    when {
        status == PendingMutationStatus.Abandoned -> Unit
        expired -> Text(stringResource(R.string.debt_adjustment_expired))
        status == PendingMutationStatus.Conflict -> Text(stringResource(R.string.debt_adjustment_conflict))
        pending.row.lastError in setOf("runtime_version_mismatch", "client_upgrade_required") ->
            Text(stringResource(R.string.sync_status_error_protocol_mismatch))
    }
    if (pending.canRetry) {
        TextButton(onClick = { recover(pending, false) }) { Text(stringResource(R.string.debt_adjustment_retry)) }
    }
    if (needsAttention) {
        TextButton(onClick = { confirmDrop = true }) { Text(stringResource(R.string.debt_adjustment_drop)) }
    }
    if (confirmDrop) AlertDialog(
        onDismissRequest = { confirmDrop = false },
        title = { Text(stringResource(R.string.debt_adjustment_drop)) },
        text = { Text(stringResource(R.string.debt_adjustment_drop_explanation)) },
        confirmButton = { TextButton(onClick = { confirmDrop = false; recover(pending, true) }) {
            Text(stringResource(R.string.debt_adjustment_drop))
        } },
        dismissButton = { TextButton(onClick = { confirmDrop = false }) { Text(stringResource(R.string.common_cancel)) } },
    )
}

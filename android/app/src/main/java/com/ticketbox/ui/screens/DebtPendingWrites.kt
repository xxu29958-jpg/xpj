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
import com.ticketbox.data.repository.PendingDebtWrite
import com.ticketbox.data.repository.DebtAmountIntent
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.settings.isExpiredFailure

@Composable
internal fun DebtWriteIntentSummary(pending: PendingDebtWrite) {
    DebtWriteRecoveryContext(pending)
    val intent = pending.intent
    if (intent == null) {
        Text(stringResource(if (pending.row.status == PendingMutationStatus.Abandoned) {
            R.string.debt_write_stopped_unreadable
        } else R.string.debt_write_unsupported))
        return
    }
    Text(intent.subject.label ?: stringResource(R.string.debt_detail_title))
    (intent as? DebtAmountIntent)?.let { amount ->
        Text(stringResource(if (pending.repayment != null) R.string.debt_repayment_pending_amount else R.string.debt_adjustment_original_amount,
            formatDisplayAmount(amount.amountCents, CurrencyDisplay.forRecord(intent.subject.homeCurrencyCode))))
    }
    pending.adjustment?.let { Text(it.request.reason) }
    pending.repayment?.let { Text(stringResource(R.string.debt_repayment_original_date, displayDateTime(it.request.paidAt))) }
    pending.debtVoid?.let { Text(stringResource(R.string.debt_action_void_title)); Text(it.request.reason) }
    pending.kind?.let { Text(stringResource(R.string.debt_kind_pending_value, stringResource(debtKindLabelRes(it.request.debtKind)))) }
    pending.repaymentVoid?.let {
        Text(stringResource(R.string.debt_action_repayment_void_title))
        Text(stringResource(R.string.debt_void_original_repayment, it.request.repaymentPublicId))
        Text(it.request.reason)
    }
    if (pending.reductionRejected) Text(stringResource(R.string.debt_adjustment_reduction_rejected))
    if (pending.requiresReview) Text(stringResource(if (pending.legacyKindAccepted) R.string.debt_kind_original_requires_review
        else R.string.debt_void_original_requires_review))
}

@Composable
private fun DebtWriteRecoveryContext(pending: PendingDebtWrite) {
    if (pending.row.status == PendingMutationStatus.Abandoned) {
        Text(stringResource(when {
            pending.legacyVoidAccepted -> R.string.debt_void_accepted_locally_stopped
            pending.legacyKindAccepted -> R.string.debt_kind_accepted_locally_stopped
            else -> R.string.debt_write_stopped_body
        }))
    }
    if (pending.originalBindingChanged && !pending.isTerminal) Text(stringResource(R.string.debt_write_original_binding_changed))
}

/** Original commands remain readable even when the canonical detail cannot be fetched. */
@Composable
internal fun DebtPendingWrites(pending: List<PendingDebtWrite>, canModify: Boolean, recover: (PendingDebtWrite, Boolean) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        pending.forEach { row -> DebtPendingWrite(row, canModify, recover) }
    }
}

@Composable
private fun DebtPendingWrite(pending: PendingDebtWrite, canModify: Boolean, recover: (PendingDebtWrite, Boolean) -> Unit) {
    var confirmDrop by rememberSaveable(pending.row.id) { mutableStateOf(false) }
    val status = pending.row.status
    HorizontalDivider()
    Text(stringResource(debtPendingWriteTitle(pending)))
    DebtWriteIntentSummary(pending)
    val expired = isExpiredFailure(pending.row.lastError)
    when {
        status == PendingMutationStatus.Abandoned -> Unit
        expired -> Text(stringResource(R.string.debt_write_expired))
        status == PendingMutationStatus.Conflict -> Text(stringResource(R.string.debt_write_conflict))
        pending.row.lastError in setOf("runtime_version_mismatch", "client_upgrade_required") ->
            Text(stringResource(R.string.sync_status_error_protocol_mismatch))
    }
    if (pending.canRetry) {
        TextButton(enabled = canModify, onClick = { recover(pending, false) }) { Text(stringResource(R.string.debt_write_retry)) }
    }
    if (pending.canStop) {
        TextButton(onClick = { confirmDrop = true }) { Text(stringResource(R.string.debt_write_drop)) }
    }
    if (confirmDrop) AlertDialog(
        onDismissRequest = { confirmDrop = false },
        title = { Text(stringResource(R.string.debt_write_drop)) },
        text = { Text(stringResource(debtWriteStopExplanation(pending))) },
        confirmButton = { TextButton(onClick = { confirmDrop = false; recover(pending, true) }) {
            Text(stringResource(R.string.debt_write_drop))
        } },
        dismissButton = { TextButton(onClick = { confirmDrop = false }) { Text(stringResource(R.string.common_cancel)) } },
    )
}

@androidx.annotation.StringRes
private fun debtPendingWriteTitle(pending: PendingDebtWrite): Int = when {
    pending.requiresReview -> if (pending.legacyKindAccepted) R.string.debt_kind_review_title else R.string.debt_void_review_title
    pending.row.status == PendingMutationStatus.Done -> when {
        pending.kind != null -> R.string.debt_kind_confirmed
        pending.isVoid -> R.string.debt_void_confirmed
        else -> R.string.debt_repayment_confirmed
    }
    pending.row.status == PendingMutationStatus.Abandoned -> R.string.debt_write_stopped
    pending.canStop -> R.string.debt_write_attention
    else -> R.string.debt_write_waiting
}

@androidx.annotation.StringRes
internal fun debtWriteStopExplanation(pending: PendingDebtWrite?): Int = when {
    pending?.legacyKindAccepted == true -> R.string.debt_kind_review_stop_explanation
    pending?.requiresReview == true -> R.string.debt_void_review_stop_explanation
    else -> R.string.debt_write_drop_explanation
}

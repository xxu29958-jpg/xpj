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
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.PendingIncomePlanSubmission
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomeSourceType
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing

@Composable
internal fun IncomePlanIntentSummary(pending: PendingIncomePlanSubmission) {
    var details by remember(pending.row.id) { mutableStateOf(false) }
    val intent = pending.intent
    if (intent == null) {
        Text(stringResource(R.string.income_plan_edit_unsupported))
    } else {
        Text(stringResource(if (pending.row.type == PendingMutationType.CreateIncomePlan)
            R.string.income_plan_submission_create else R.string.sync_status_mutation_update_income_plan))
        Text(intent.originalLabel + " · " + intent.request.intentMonth)
        Text((intent.request.label ?: intent.originalLabel) + " · " + intent.homeCurrencyCode + " · " +
            formatDisplayAmount(intent.request.amountCents ?: intent.originalAmountCents,
                CurrencyDisplay.forRecord(intent.homeCurrencyCode)))
        intent.request.sourceType?.let { Text(IncomeSourceType.fromWire(it).displayName) }
        intent.request.frequency?.let { Text(IncomeFrequency.fromWire(it).displayName) }
        intent.request.incomeMonth?.let { Text(stringResource(R.string.income_plan_edit_target_month, it)) }
        intent.request.payDay?.let { Text(stringResource(R.string.income_plan_submission_pay_day, it)) }
    }
    TextButton(onClick = { details = !details }) { Text(stringResource(R.string.income_plan_submission_details)) }
    if (details) {
        Text(stringResource(R.string.income_plan_submission_key, pending.row.idempotencyKey.orEmpty()))
        Text(stringResource(R.string.income_plan_submission_version, pending.row.expectedRowVersion))
    }
}

/** Original submissions remain reachable when the management query is unavailable. */
@Composable
internal fun IncomePlanPendingSubmissions(rows: List<PendingIncomePlanSubmission>, selected: Long?, canModify: Boolean,
    recover: (PendingIncomePlanSubmission, Boolean) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        if (selected != null && rows.none { it.row.id == selected }) Text(stringResource(R.string.income_plan_submission_unavailable))
        rows.filter { !it.isConfirmed || it.row.id == selected }
            .sortedBy { if (it.row.id == selected) 0 else 1 }
            .forEach { pending -> IncomePlanPendingSubmission(pending, canModify, recover) }
    }
}

@Composable
private fun IncomePlanPendingSubmission(pending: PendingIncomePlanSubmission, canModify: Boolean,
    recover: (PendingIncomePlanSubmission, Boolean) -> Unit) {
    var confirmDrop by remember(pending.row.id) { mutableStateOf(false) }
    val dropLabel = stringResource(if (pending.requiresReview) R.string.income_plan_submission_stop_record else R.string.income_plan_edit_drop)
    HorizontalDivider()
    Text(stringResource(when {
        pending.requiresReview -> R.string.income_plan_submission_review
        !pending.hasSupportedIntent -> R.string.income_plan_edit_unsupported
        pending.isConfirmed -> R.string.income_plan_submission_done
        pending.row.status in setOf(PendingMutationStatus.Pending, PendingMutationStatus.InFlight) -> R.string.income_plan_edit_waiting
        else -> R.string.income_plan_edit_attention
    }))
    IncomePlanIntentSummary(pending)
    if (pending.row.status == PendingMutationStatus.Conflict) Text(stringResource(R.string.income_plan_edit_conflict))
    if (pending.canRetry && canModify) TextButton(onClick = { recover(pending, false) }) {
        Text(stringResource(R.string.income_plan_edit_retry))
    }
    if (pending.canDrop) TextButton(onClick = { confirmDrop = true }) { Text(dropLabel) }
    if (confirmDrop) AlertDialog(onDismissRequest = { confirmDrop = false },
        title = { Text(dropLabel) },
        text = { Column { IncomePlanIntentSummary(pending); Text(stringResource(if (pending.requiresReview)
            R.string.income_plan_submission_stop_record_explanation else R.string.income_plan_edit_drop_explanation)) } },
        confirmButton = { TextButton(onClick = { confirmDrop = false; recover(pending, true) }) {
            Text(dropLabel)
        } },
        dismissButton = { TextButton(onClick = { confirmDrop = false }) { Text(stringResource(R.string.common_cancel)) } })
}

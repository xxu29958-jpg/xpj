package com.ticketbox.ui.screens.settings.categoryrules

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
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.PendingCategoryRuleSubmission
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.formatDisplayAmount

@Composable
internal fun categoryRuleAmountText(amount: Long, code: String?): String {
    val currency = CurrencyCode.fromStorageKeyOrNull(code)
    return if (currency != null) "${currency.storageKey} ${formatDisplayAmount(amount, CurrencyDisplay(currency))}"
    else formatDisplayAmount(amount, CurrencyDisplay.forRecord(code ?: stringResource(R.string.category_rule_currency_unknown)))
}

@Composable
internal fun CategoryRuleSubmissionSummary(pending: PendingCategoryRuleSubmission) {
    var details by remember(pending.row.id) { mutableStateOf(false) }
    Column {
        val request = pending.request
        Text(stringResource(when (pending.row.type) {
            PendingMutationType.CreateCategoryRule -> R.string.category_rule_submission_create
            PendingMutationType.DeleteCategoryRule -> R.string.sync_status_mutation_delete_category_rule
            else -> R.string.sync_status_mutation_update_category_rule
        }))
        Text(request?.keyword ?: stringResource(R.string.category_rule_submission_unknown))
        request?.category?.let { Text(it) }
        if (request?.priority != null && request.enabled != null) Text(stringResource(
            R.string.category_rule_card_priority_status, request.priority,
            stringResource(if (request.enabled) R.string.category_rule_card_status_enabled else R.string.category_rule_card_status_disabled)))
        if (request != null && request.amountMinCents == null && request.amountMaxCents == null) {
            Text(stringResource(R.string.category_rule_amount_unlimited))
        }
        request?.sourceContains?.let { Text(stringResource(R.string.category_rule_condition_source_contains, it)) }
        request?.tagContains?.let { Text(stringResource(R.string.category_rule_condition_tag, it)) }
        request?.amountMinCents?.let { Text(stringResource(R.string.category_rule_condition_amount_min,
            categoryRuleAmountText(it, request.homeCurrencyCode))) }
        request?.amountMaxCents?.let { Text(stringResource(R.string.category_rule_condition_amount_max,
            categoryRuleAmountText(it, request.homeCurrencyCode))) }
        TextButton(onClick = { details = !details }) { Text(stringResource(R.string.category_rule_submission_details)) }
        if (details) {
            Text(stringResource(R.string.category_rule_submission_key, pending.row.idempotencyKey.orEmpty()))
            Text(stringResource(R.string.category_rule_submission_version, pending.row.expectedRowVersion))
        }
    }
}

@Composable
internal fun CategoryRuleSubmissionCards(rows: List<PendingCategoryRuleSubmission>, selected: Long?, busy: Boolean,
    readOnly: Boolean, recover: (PendingCategoryRuleSubmission, Boolean) -> Unit) {
    var stopping by remember { mutableStateOf<PendingCategoryRuleSubmission?>(null) }
    val shown = rows.filter { !it.isDone || it.row.id == selected }
        .sortedBy { if (it.row.id == selected) 0 else 1 }
    if (selected != null && rows.none { it.row.id == selected }) AppContentCard {
        Text(stringResource(R.string.category_rule_submission_unavailable))
    }
    shown.forEach { pending ->
        AppContentCard {
            CategoryRuleSubmissionSummary(pending)
            Text(stringResource(when {
                !pending.supported -> R.string.category_rule_submission_review
                pending.isDone -> R.string.category_rule_submission_done
                else -> R.string.category_rule_submission_waiting
            }))
            if (pending.canRetry && !readOnly) TextButton(enabled = !busy, onClick = { recover(pending, false) }) {
                Text(stringResource(R.string.category_rule_submission_retry))
            }
            if (pending.canDrop) TextButton(enabled = !busy, onClick = { stopping = pending }) {
                Text(stringResource(R.string.category_rule_submission_stop))
            }
        }
    }
    stopping?.let { original ->
        AlertDialog(onDismissRequest = { stopping = null },
            title = { Text(stringResource(R.string.category_rule_submission_stop)) },
            text = { Column { CategoryRuleSubmissionSummary(original); Text(stringResource(R.string.category_rule_submission_stop_body)) } },
            confirmButton = { TextButton(enabled = !busy, onClick = { stopping = null; recover(original, true) }) {
                Text(stringResource(R.string.category_rule_submission_stop)) } },
            dismissButton = { TextButton(onClick = { stopping = null }) { Text(stringResource(R.string.common_cancel)) } })
    }
}

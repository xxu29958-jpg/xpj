package com.ticketbox.ui.screens.expense.fact

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
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
import com.ticketbox.data.repository.PendingExpenseCorrection
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.settings.friendlyLastError

internal data class CorrectionSubmissionOptions(val canModify: Boolean, val busy: Boolean, val refreshPending: Boolean)
internal data class CorrectionSubmissionActions(val recover: (Boolean) -> Unit, val reviewFact: (() -> Unit)? = null)

/** The same original-submission consumer in detail and both global recovery entrances. */
@Composable
internal fun ExpenseCorrectionSubmissionCard(
    pending: PendingExpenseCorrection,
    options: CorrectionSubmissionOptions,
    actions: CorrectionSubmissionActions,
) {
    val (canModify, busy) = options
    val refreshPending = options.refreshPending || pending.refreshRequired
    val (recover, reviewFact) = actions
    var confirmDrop by rememberSaveable(pending.row.id) { mutableStateOf(false) }
    var expanded by rememberSaveable(pending.row.id) { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        HorizontalDivider()
        Text(stringResource(R.string.correction_submission_title), style = MaterialTheme.typography.titleSmall)
        Text(correctionStatusText(pending, refreshPending))
        pending.intent?.originalMerchant?.let { Text(it) }
        val request = pending.intent?.request ?: pending.legacyRequest
        request?.let { Text(stringResource(R.string.correction_submission_reason, it.reason)) }
        TextButton(onClick = { expanded = !expanded }) { Text(stringResource(R.string.correction_submission_details)) }
        if (expanded) CorrectionSubmissionFields(pending)
        if (pending.canRetry) TextButton(onClick = { recover(false) }, enabled = canModify && !busy) {
            Text(stringResource(R.string.correction_submission_retry))
        }
        if (reviewFact != null && (pending.canDiscard || pending.delivered && refreshPending)) {
            TextButton(onClick = reviewFact, enabled = !busy) { Text(stringResource(R.string.correction_submission_review)) }
        }
        if (pending.canDiscard) TextButton(onClick = { confirmDrop = true }, enabled = !busy) {
            Text(stringResource(R.string.correction_submission_drop))
        }
    }
    if (confirmDrop) AlertDialog(onDismissRequest = { confirmDrop = false },
        title = { Text(stringResource(R.string.correction_submission_drop)) },
        text = { Text(stringResource(R.string.correction_submission_drop_explanation)) },
        confirmButton = { TextButton(onClick = { confirmDrop = false; recover(true) }, enabled = !busy) {
            Text(stringResource(R.string.correction_submission_drop))
        } },
        dismissButton = { TextButton(onClick = { confirmDrop = false }) { Text(stringResource(R.string.common_cancel)) } })
}

@Composable
private fun correctionStatusText(pending: PendingExpenseCorrection, refreshPending: Boolean): String {
    val fallback = stringResource(when {
        !pending.hasSupportedIntent -> R.string.correction_submission_unsupported
        pending.row.lastError == "outbox_row_expired" -> R.string.correction_submission_expired
        pending.row.status == PendingMutationStatus.Failed && !pending.canRetry -> R.string.correction_submission_review_required
        pending.delivered -> if (refreshPending) R.string.expense_correction_saved_refresh_pending else R.string.expense_correction_saved
        pending.row.status == PendingMutationStatus.Conflict -> R.string.correction_submission_conflict
        pending.row.status == PendingMutationStatus.InFlight -> R.string.correction_submission_sending
        pending.row.status == PendingMutationStatus.Pending -> R.string.expense_correction_queued
        else -> R.string.correction_submission_failed
    })
    return if (pending.canRetry) friendlyLastError(pending.row.lastError, fallback) else fallback
}

@Composable
private fun CorrectionSubmissionFields(pending: PendingExpenseCorrection) {
    val request = pending.intent?.request ?: pending.legacyRequest ?: return
    val currency = request.originalCurrencyCode ?: pending.intent?.originalCurrencyCode
    val homeCurrency = pending.intent?.homeCurrencyCode
    val clear = stringResource(R.string.correction_submission_clear)
    pending.intent?.let { Text(stringResource(R.string.correction_submission_original,
        correctionAmount(it.originalAmountMinor, it.originalCurrencyCode))) }
    request.originalAmountMinor?.let { Text(stringResource(R.string.correction_submission_amount, correctionAmount(it, currency))) }
    request.originalCurrencyCode?.let { CorrectionField(R.string.correction_field_currency, it) }
    request.amountCents?.let { CorrectionField(R.string.correction_field_home_amount, correctionAmount(it, homeCurrency)) }
    CorrectionScalarFields(request, clear)
    CorrectionCollectionFields(request, homeCurrency)
}

@Composable
private fun CorrectionScalarFields(request: com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto, clear: String) {
    request.merchant?.let { CorrectionField(R.string.correction_field_merchant, it.ifEmpty { clear }) }
    request.category?.let { CorrectionField(R.string.correction_field_category, it.ifEmpty { clear }) }
    request.note?.let { CorrectionField(R.string.correction_field_note, it.ifEmpty { clear }) }
    request.tags?.let { CorrectionField(R.string.correction_field_tags, it.ifEmpty { clear }) }
    if (request.expenseTime.changed) CorrectionField(R.string.correction_field_time, request.expenseTime.value ?: clear)
    if (request.valueScore.changed) CorrectionField(R.string.correction_field_value, request.valueScore.value?.toString() ?: clear)
    if (request.regretScore.changed) CorrectionField(R.string.correction_field_regret, request.regretScore.value?.toString() ?: clear)
}

@Composable
private fun CorrectionCollectionFields(request: com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto, homeCurrency: String?) {
    request.items?.let { items ->
        CorrectionField(R.string.correction_field_items, items.size.toString())
        items.forEach { item ->
            Text(item.name + " · " + correctionAmount(item.amountCents, homeCurrency))
            listOfNotNull(item.quantityText, item.category, item.rawText).forEach { Text(it) }
            item.unitPriceCents?.let { Text(correctionAmount(it, homeCurrency)) }
        }
    }
    request.splits?.let { splits ->
        CorrectionField(R.string.correction_field_splits, splits.size.toString())
        splits.forEach { split ->
            Text(stringResource(R.string.correction_submission_member, split.memberId) + " · " +
                correctionAmount(split.amountCents, homeCurrency))
            split.note?.let { Text(it) }
        }
    }
}

@Composable
private fun CorrectionField(label: Int, value: String) { Text(stringResource(label) + "：" + value) }

@Composable
private fun correctionAmount(amount: Long?, currency: String?): String = when {
    amount == null -> stringResource(R.string.correction_submission_unknown_amount)
    currency == null -> stringResource(R.string.correction_submission_unknown_currency, amount)
    else -> formatDisplayAmount(amount, CurrencyDisplay.forRecord(currency))
}

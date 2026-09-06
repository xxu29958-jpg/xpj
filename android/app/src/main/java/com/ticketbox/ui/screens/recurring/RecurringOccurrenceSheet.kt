package com.ticketbox.ui.screens.recurring

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.PendingOccurrencePayment
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.ExpenseFilterCriteria
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.filterConfirmedStreamItems
import com.ticketbox.domain.model.recordCurrencyDisplay
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.RecurringOccurrenceUiState

data class OccurrenceSheetActions(
    val onDismiss: () -> Unit,
    val onRefresh: () -> Unit,
    val onPeriod: (String) -> Unit,
    val onChoose: (ConfirmedStreamItem.ExpenseRow?) -> Unit,
    val onSubmit: () -> Unit,
    val onRecover: (PendingOccurrencePayment, Boolean) -> Unit,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RecurringOccurrenceSheet(
    state: RecurringOccurrenceUiState,
    currency: CurrencyDisplay,
    actions: OccurrenceSheetActions,
) {
    val item = state.item ?: return
    ModalBottomSheet(onDismissRequest = actions.onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        AppSheetScaffold(title = item.merchant, subtitle = stringResource(R.string.occurrence_subtitle)) {
            OccurrencePeriodControls(state, actions)
            state.message?.let { Text(it, modifier = Modifier.testTag("occurrence-message")) }
            state.occurrence?.let { occurrence ->
                Text(stringResource(occurrenceStateLabel(occurrence.state)), modifier = Modifier.testTag("occurrence-state"))
                Text(stringResource(R.string.occurrence_reserved, formatDisplayAmount(occurrence.reservedAmountCents, currency)))
                occurrence.paidAmountCents?.let { Text(stringResource(R.string.occurrence_paid_amount, formatDisplayAmount(it, currency))) }
                Text(stringResource(R.string.occurrence_next_due, occurrence.nextDueDate ?: stringResource(R.string.occurrence_no_reminder)))
                if (occurrence.expensePublicId != null) {
                    TextButton(onClick = { actions.onChoose(null) }, enabled = state.canWrite) { Text(stringResource(R.string.occurrence_clear)) }
                }
                if (state.access?.canModify == false) Text(stringResource(R.string.occurrence_readonly))
                OccurrenceChoice(state, currency, actions.onSubmit)
                state.pending.forEach { OccurrencePending(it, actions.onRecover) }
                if (state.canWrite) OccurrencePaymentPicker(state, actions.onChoose)
            }
        }
    }
}

@Composable
private fun OccurrencePeriodControls(state: RecurringOccurrenceUiState, actions: OccurrenceSheetActions) {
    var period by rememberSaveable(state.item?.publicId, state.occurrence?.period) { mutableStateOf(state.occurrence?.period.orEmpty()) }
    OutlinedTextField(value = period, onValueChange = { period = it }, label = { Text(stringResource(R.string.occurrence_period)) },
        singleLine = true, modifier = Modifier.fillMaxWidth().testTag("occurrence-period"))
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        TextButton(onClick = { actions.onPeriod(period) }, enabled = !state.loading && !state.saving) { Text(stringResource(R.string.occurrence_show_period)) }
        TextButton(onClick = actions.onRefresh, enabled = !state.loading && !state.saving) { Text(stringResource(R.string.occurrence_refresh)) }
    }
    if (state.loading) Text(stringResource(R.string.occurrence_loading))
}

@Composable
private fun OccurrenceChoice(state: RecurringOccurrenceUiState, currency: CurrencyDisplay, submit: () -> Unit) {
    val choice = state.choice ?: return
    val label = if (choice.request.action == "clear") stringResource(R.string.occurrence_clear_review)
        else stringResource(R.string.occurrence_link_review, choice.paymentLabel.orEmpty(), formatDisplayAmount(choice.paymentAmountCents ?: 0, currency))
    Text(label)
    AppPrimaryButton(text = stringResource(R.string.occurrence_submit), onClick = submit,
        enabled = state.canWrite, modifier = Modifier.fillMaxWidth().testTag("occurrence-submit"))
}

@Composable
private fun OccurrencePending(pending: PendingOccurrencePayment, recover: (PendingOccurrencePayment, Boolean) -> Unit) {
    var confirmDrop by rememberSaveable(pending.row.id) { mutableStateOf(false) }
    val intent = pending.intent
    HorizontalDivider()
    Text(stringResource(if (pending.row.status in setOf(PendingMutationStatus.Pending, PendingMutationStatus.InFlight))
        R.string.occurrence_pending else R.string.occurrence_attention))
    if (intent == null) Text(stringResource(R.string.occurrence_unsupported))
    else Text(stringResource(R.string.occurrence_original_intent, intent.period,
        if (intent.request.action == "clear") stringResource(R.string.occurrence_clear) else intent.paymentLabel.orEmpty()))
    if (pending.row.status == PendingMutationStatus.Failed) {
        TextButton(onClick = { recover(pending, false) }, enabled = intent != null) { Text(stringResource(R.string.occurrence_retry_original)) }
    }
    if (pending.row.status in setOf(PendingMutationStatus.Conflict, PendingMutationStatus.Failed)) {
        TextButton(onClick = { confirmDrop = true }) { Text(stringResource(R.string.occurrence_drop)) }
    }
    if (confirmDrop) AlertDialog(onDismissRequest = { confirmDrop = false },
        title = { Text(stringResource(R.string.occurrence_drop)) }, text = { Text(stringResource(R.string.occurrence_drop_explanation)) },
        confirmButton = { TextButton(onClick = { confirmDrop = false; recover(pending, true) }) { Text(stringResource(R.string.occurrence_drop)) } },
        dismissButton = { TextButton(onClick = { confirmDrop = false }) { Text(stringResource(R.string.occurrence_keep)) } })
}

@Composable
private fun OccurrencePaymentPicker(state: RecurringOccurrenceUiState, choose: (ConfirmedStreamItem.ExpenseRow) -> Unit) {
    var month by rememberSaveable(state.occurrence?.period) { mutableStateOf(state.occurrence?.period.orEmpty()) }
    var query by rememberSaveable(state.item?.publicId) { mutableStateOf("") }
    val payments = occurrencePaymentChoices(state.payments, month, query)
    HorizontalDivider()
    Text(stringResource(R.string.occurrence_pick_explanation))
    OutlinedTextField(value = month, onValueChange = { month = it }, singleLine = true,
        label = { Text(stringResource(R.string.occurrence_payment_month)) }, modifier = Modifier.fillMaxWidth())
    OutlinedTextField(value = query, onValueChange = { query = it }, singleLine = true,
        label = { Text(stringResource(R.string.occurrence_search)) }, modifier = Modifier.fillMaxWidth())
    if (payments.isEmpty()) Text(stringResource(R.string.occurrence_no_payments))
    if (payments.size > 20) Text(stringResource(R.string.occurrence_narrow_search))
    payments.take(20).forEach { payment ->
        TextButton(onClick = { choose(payment) }, modifier = Modifier.fillMaxWidth().testTag("occurrence-payment-" + payment.root.id)) {
            Text(payment.streamDate + " · " + payment.root.merchant.orEmpty() + " · " +
                formatDisplayAmount(payment.root.amountCents ?: 0, payment.root.recordCurrencyDisplay()) +
                if (payment.lineageStatus != ExpenseLineageStatus.Confirmed) stringResource(R.string.occurrence_has_refund) else "")
        }
    }
}

internal fun occurrencePaymentChoices(rows: List<ConfirmedStreamItem>, month: String, query: String): List<ConfirmedStreamItem.ExpenseRow> =
    filterConfirmedStreamItems(rows, ExpenseFilterCriteria(month = month, query = query))
        .filterIsInstance<ConfirmedStreamItem.ExpenseRow>().filter {
            it.root.id > 0 && !it.root.pendingSync && it.root.status == "confirmed" &&
                it.root.amountCents != null && it.lineageStatus != ExpenseLineageStatus.Reversed
        }.sortedByDescending { it.streamDate }

private fun occurrenceStateLabel(state: String): Int = when (state) {
    "fulfilled" -> R.string.occurrence_fulfilled
    "needs_review" -> R.string.occurrence_review
    "unfulfilled" -> R.string.occurrence_unfulfilled
    else -> R.string.occurrence_unknown
}

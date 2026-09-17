package com.ticketbox.ui.screens.recurring

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Check
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
import com.ticketbox.domain.model.ExpenseFilterCriteria
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.domain.model.filterConfirmedStreamItems
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.RecurringOccurrenceUiState

data class OccurrencePaymentGuard(
    val resolved: Boolean = true,
    val conflict: Boolean = false,
    val leftoverBlocked: Boolean = false,
    val leftoverUnreadable: Boolean = false,
    val leftoverContinueDraft: Boolean = false,
    val leftoverExistingOrigin: Boolean = false,
    val leftoverActionFailed: Boolean = false,
)

data class OccurrenceSheetActions(
    val onDismiss: () -> Unit,
    val onRefresh: () -> Unit,
    val onPeriod: (String) -> Unit,
    val onChoose: (ConfirmedStreamItem.ExpenseRow?) -> Unit,
    val onSubmit: () -> Unit,
    val onRecover: (PendingOccurrencePayment, Boolean) -> Unit,
    val onOpenExpense: (Long) -> Unit = {},
    val onRecordPayment: () -> Unit = {},
    val onAbandonLeftover: () -> Unit = {},
    val onContinueLeftover: () -> Unit = {},
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun RecurringOccurrenceSheet(
    state: RecurringOccurrenceUiState,
    actions: OccurrenceSheetActions,
    preferredExpenseId: Long? = null,
    origin: OccurrencePaymentGuard = OccurrencePaymentGuard(),
) {
    val item = state.item ?: return
    ModalBottomSheet(onDismissRequest = actions.onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        AppSheetScaffold(title = item.merchant, subtitle = stringResource(R.string.occurrence_subtitle)) {
            OccurrencePeriodControls(state, actions)
            state.message?.let { Text(it.asString(), modifier = Modifier.testTag("occurrence-message")) }
            OccurrencePaymentConflict(origin, actions.onAbandonLeftover, actions.onContinueLeftover)
            state.seriesPending.forEach { OccurrencePending(it, state.access?.canModify == true, actions.onRecover) }
            state.occurrence?.let { occurrence ->
                Text(stringResource(occurrenceStateLabel(occurrence.state)), modifier = Modifier.testTag("occurrence-state"))
                Text(stringResource(R.string.occurrence_reserved, recurringRecordedAmountText(occurrence.reservedAmountCents, occurrence.homeCurrencyCode)))
                occurrence.paidAmountCents?.let {
                    Text(stringResource(R.string.occurrence_paid_amount, recurringRecordedAmountText(it, occurrence.paidHomeCurrencyCode)))
                }
                occurrence.expenseId?.let { id ->
                    TextButton(onClick = { actions.onOpenExpense(id) }) { Text(stringResource(R.string.occurrence_open_payment)) }
                }
                Text(stringResource(R.string.occurrence_next_due, occurrence.nextDueDate ?: stringResource(R.string.occurrence_no_reminder)))
                if (occurrence.expensePublicId != null) {
                    TextButton(onClick = { actions.onChoose(null) }, enabled = state.canWrite) { Text(stringResource(R.string.occurrence_clear)) }
                }
                if (state.access?.canModify == false) Text(stringResource(R.string.occurrence_readonly))
                OccurrenceRecordPayment(
                    canWrite = state.canWrite,
                    unfulfilled = occurrence.state == "unfulfilled",
                    origin = origin,
                    onRecord = actions.onRecordPayment,
                )
                OccurrenceChoice(state, actions.onSubmit)
                if (state.canWrite) OccurrencePaymentPicker(state, actions.onChoose, preferredExpenseId)
            }
        }
    }
}

@Composable
private fun OccurrencePaymentConflict(
    origin: OccurrencePaymentGuard,
    onAbandonLeftover: () -> Unit,
    onContinueLeftover: () -> Unit,
) {
    if (origin.conflict) {
        Text(
            stringResource(R.string.recurring_payment_origin_conflict),
            modifier = Modifier.testTag("occurrence-payment-conflict"),
        )
        return
    }
    if (!origin.leftoverBlocked) return
    var confirmUnreadable by rememberSaveable { mutableStateOf(false) }
    Text(
        stringResource(R.string.recurring_payment_leftover_unresolved),
        modifier = Modifier.testTag("occurrence-payment-leftover"),
    )
    LeftoverPaymentNotices(origin)
    if (origin.leftoverContinueDraft) {
        TextButton(
            onClick = onContinueLeftover,
            modifier = Modifier.testTag("occurrence-payment-leftover-continue"),
        ) {
            Text(stringResource(R.string.recurring_payment_leftover_continue))
        }
    }
    TextButton(
        onClick = { if (origin.leftoverUnreadable) confirmUnreadable = true else onAbandonLeftover() },
        modifier = Modifier.testTag("occurrence-payment-leftover-abandon"),
    ) {
        Text(stringResource(R.string.recurring_payment_leftover_abandon))
    }
    if (!confirmUnreadable) return
    AlertDialog(
        onDismissRequest = { confirmUnreadable = false },
        text = {
            Text(
                stringResource(R.string.recurring_payment_leftover_abandon_unreadable),
                modifier = Modifier.testTag("occurrence-payment-leftover-abandon-unreadable"),
            )
        },
        confirmButton = {
            TextButton(
                onClick = { confirmUnreadable = false; onAbandonLeftover() },
                modifier = Modifier.testTag("occurrence-payment-leftover-abandon-confirm"),
            ) { Text(stringResource(R.string.recurring_payment_leftover_abandon_confirm)) }
        },
        dismissButton = {
            TextButton(onClick = { confirmUnreadable = false }) {
                Text(stringResource(R.string.occurrence_keep))
            }
        },
    )
}

@Composable
private fun LeftoverPaymentNotices(origin: OccurrencePaymentGuard) {
    if (origin.leftoverExistingOrigin) {
        Text(
            stringResource(R.string.recurring_payment_leftover_existing_origin),
            modifier = Modifier.testTag("occurrence-payment-leftover-existing-origin"),
        )
    }
    if (origin.leftoverActionFailed) {
        Text(
            stringResource(R.string.recurring_payment_leftover_action_failed),
            modifier = Modifier.testTag("occurrence-payment-leftover-action-failed"),
        )
    }
}

@Composable
private fun OccurrenceRecordPayment(
    canWrite: Boolean,
    unfulfilled: Boolean,
    origin: OccurrencePaymentGuard,
    onRecord: () -> Unit,
) {
    if (!canWrite || !unfulfilled) return
    AppPrimaryButton(
        text = stringResource(R.string.occurrence_record_payment),
        icon = Icons.Filled.Add,
        onClick = onRecord,
        enabled = origin.resolved && !origin.conflict && !origin.leftoverBlocked,
        modifier = Modifier.fillMaxWidth().testTag("occurrence-record-payment"),
    )
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
private fun OccurrenceChoice(state: RecurringOccurrenceUiState, submit: () -> Unit) {
    val choice = state.choice ?: return
    val label = if (choice.request.action == "clear") stringResource(R.string.occurrence_clear_review)
        else stringResource(R.string.occurrence_link_review, choice.paymentLabel.orEmpty(),
            occurrencePaymentAmountText(choice.paymentAmountCents, choice.paymentCurrencyCode))
    Text(label)
    AppPrimaryButton(text = stringResource(R.string.occurrence_submit), icon = Icons.Filled.Check, onClick = submit,
        enabled = state.canWrite, modifier = Modifier.fillMaxWidth().testTag("occurrence-submit"))
}

@Composable
private fun OccurrencePending(pending: PendingOccurrencePayment, canModify: Boolean, recover: (PendingOccurrencePayment, Boolean) -> Unit) {
    var confirmDrop by rememberSaveable(pending.row.id) { mutableStateOf(false) }
    HorizontalDivider()
    Text(stringResource(if (pending.row.status in setOf(PendingMutationStatus.Pending, PendingMutationStatus.InFlight))
        R.string.occurrence_pending else R.string.occurrence_attention))
    RecurringOccurrenceIntentSummary(pending)
    if (pending.canRetry && canModify) {
        TextButton(onClick = { recover(pending, false) }) { Text(stringResource(R.string.occurrence_retry_original)) }
    }
    if (pending.row.status in setOf(PendingMutationStatus.Conflict, PendingMutationStatus.Failed)) {
        TextButton(onClick = { confirmDrop = true }) { Text(stringResource(R.string.occurrence_drop)) }
    }
    if (confirmDrop) AlertDialog(onDismissRequest = { confirmDrop = false },
        title = { Text(stringResource(R.string.occurrence_drop)) }, text = {
            androidx.compose.foundation.layout.Column {
                RecurringOccurrenceIntentSummary(pending)
                Text(stringResource(R.string.occurrence_drop_explanation))
            }
        },
        confirmButton = { TextButton(onClick = { confirmDrop = false; recover(pending, true) }) { Text(stringResource(R.string.occurrence_drop)) } },
        dismissButton = { TextButton(onClick = { confirmDrop = false }) { Text(stringResource(R.string.occurrence_keep)) } })
}

@Composable
private fun OccurrencePaymentPicker(
    state: RecurringOccurrenceUiState,
    choose: (ConfirmedStreamItem.ExpenseRow) -> Unit,
    preferredExpenseId: Long?,
) {
    var month by rememberSaveable(state.occurrence?.period) { mutableStateOf(state.occurrence?.period.orEmpty()) }
    var query by rememberSaveable(state.item?.publicId) { mutableStateOf("") }
    val payments = occurrencePaymentChoices(state.payments, month, query, preferredExpenseId)
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
                occurrencePaymentAmountText(payment.root.amountCents, payment.root.homeCurrencyCode) +
                if (payment.lineageStatus != ExpenseLineageStatus.Confirmed) stringResource(R.string.occurrence_has_refund) else "")
        }
    }
}

internal fun occurrencePaymentChoices(
    rows: List<ConfirmedStreamItem>,
    month: String,
    query: String,
    preferredExpenseId: Long? = null,
): List<ConfirmedStreamItem.ExpenseRow> {
    val eligible = filterConfirmedStreamItems(rows, ExpenseFilterCriteria(month = "", query = ""))
        .filterIsInstance<ConfirmedStreamItem.ExpenseRow>().filter {
            it.root.id > 0 && !it.root.pendingSync && it.root.status == "confirmed" &&
                it.root.amountCents != null && it.lineageStatus != ExpenseLineageStatus.Reversed
        }
    val preferred = eligible.filter { it.root.id == preferredExpenseId }
    val ordinary = filterConfirmedStreamItems(rows, ExpenseFilterCriteria(month = month, query = query))
        .filterIsInstance<ConfirmedStreamItem.ExpenseRow>().filter {
            it.root.id > 0 && !it.root.pendingSync && it.root.status == "confirmed" &&
                it.root.amountCents != null && it.lineageStatus != ExpenseLineageStatus.Reversed &&
                it.root.id != preferredExpenseId
        }.sortedByDescending { it.streamDate }
    return preferred + ordinary
}

private fun occurrenceStateLabel(state: String): Int = when (state) {
    "fulfilled" -> R.string.occurrence_fulfilled
    "needs_review" -> R.string.occurrence_review
    "unfulfilled" -> R.string.occurrence_unfulfilled
    else -> R.string.occurrence_unknown
}

package com.ticketbox.ui.screens.recurring

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.outlined.ReceiptLong
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
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
import com.ticketbox.ui.components.AppButtonIcons
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppBusyGuardedSheet
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.SettingsEntryIcon
import com.ticketbox.presentation.displayCalendarDay
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.RecurringOccurrenceUiState

data class OccurrencePaymentGuard(
    val resolved: Boolean = true,
    val conflict: Boolean = false,
    val localDraftHeld: Boolean = false,
    val priorGenerationOccupied: Boolean = false,
    val priorRetireBusy: Boolean = false,
    val priorRetireFailed: Boolean = false,
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
    val onOpenOrigin: () -> Unit = {},
    val onContinueLocalDraft: () -> Unit = {},
    val onAbandonLocalDraft: () -> Unit = {},
    val onRetirePriorOrigin: () -> Unit = {},
)

@Composable
private fun OccurrenceReminderDate(nextDueDate: String?, ledgerToday: java.time.LocalDate?) {
    val label = when (nextDueDate?.let { recurringDueIsPast(it, ledgerToday) }) {
        true -> R.string.occurrence_past_due
        false -> R.string.occurrence_next_due
        null -> R.string.occurrence_reminder_date
    }
    Text(stringResource(label,
        nextDueDate?.let(::displayCalendarDay) ?: stringResource(R.string.occurrence_no_reminder)),
        style = MaterialTheme.typography.bodyMedium)
}

@Composable
fun RecurringOccurrenceSheet(
    state: RecurringOccurrenceUiState,
    actions: OccurrenceSheetActions,
    preferredExpenseId: Long? = null,
    origin: OccurrencePaymentGuard = OccurrencePaymentGuard(),
    ledgerToday: java.time.LocalDate? = null,
) {
    val item = state.item ?: return
    val paymentFilters = rememberSaveableStateHolder()
    AppBusyGuardedSheet(isSubmitting = state.saving, onDismiss = actions.onDismiss, skipPartiallyExpanded = true) {
        AppSheetScaffold(
            title = item.merchant,
            subtitle = stringResource(R.string.occurrence_subtitle),
            modifier = Modifier.fillMaxHeight(),
            actions = occurrenceChoiceActions(state, actions),
        ) {
            state.occurrence?.let { OccurrenceCurrentSummary(it) }
            state.message?.let { Text(it.asString(), modifier = Modifier.testTag("occurrence-message")) }
            OccurrencePaymentConflict(origin, actions)
            state.seriesPending.forEach { OccurrencePending(it, state.access?.canModify == true, actions.onRecover) }
            state.occurrence?.let { occurrence ->
                if (occurrence.expensePublicId != null) {
                    TextButton(onClick = { actions.onChoose(null) }, enabled = state.canWrite) { Text(stringResource(R.string.occurrence_clear)) }
                }
                if (state.access?.canModify == false) Text(stringResource(R.string.occurrence_readonly),
                    style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                OccurrenceReminderDate(occurrence.nextDueDate, ledgerToday)
            }
            state.occurrence?.let { occurrence ->
                if (state.canWrite) paymentFilters.SaveableStateProvider("${item.publicId}:${occurrence.period}") {
                    OccurrencePaymentPicker(state, actions.onChoose, preferredExpenseId)
                }
                OccurrenceRecordPayment(
                    canWrite = state.canWrite,
                    unfulfilled = occurrence.state == "unfulfilled",
                    origin = origin,
                    onRecord = actions.onRecordPayment,
                )
            }
            RecurringReadSource(state.fetchedAt, state.fromCache, state.loading)
            if (state.fromCache && state.requestedPeriod == "current") {
                Text(stringResource(R.string.occurrence_cached_period, state.occurrence?.period.orEmpty()))
            }
            OccurrencePeriodControls(state, actions)
            state.occurrence?.let { OccurrenceDefinitionBasis(it) }
        }
    }
}

@Composable
private fun OccurrencePaymentConflict(
    origin: OccurrencePaymentGuard,
    actions: OccurrenceSheetActions,
) {
    if (origin.conflict) {
        Text(
            stringResource(R.string.recurring_payment_origin_conflict),
            modifier = Modifier.testTag("occurrence-payment-conflict"),
        )
        return
    }
    if (origin.priorGenerationOccupied) {
        var confirmRetire by rememberSaveable { mutableStateOf(false) }
        Text(stringResource(R.string.recurring_payment_prior_generation_occupied), modifier = Modifier.testTag("occurrence-payment-prior-origin"))
        TextButton(actions.onOpenOrigin, Modifier.testTag("occurrence-payment-prior-origin-view")) {
            Text(stringResource(R.string.recurring_payment_local_draft_view_origin))
        }
        TextButton({ if (!origin.priorRetireBusy) confirmRetire = true }, Modifier.testTag("occurrence-payment-prior-origin-retire"), enabled = !origin.priorRetireBusy) {
            Text(stringResource(R.string.recurring_payment_retire_prior_origin))
        }
        if (origin.priorRetireFailed) {
            Text(stringResource(R.string.recurring_payment_retire_prior_active), modifier = Modifier.testTag("occurrence-payment-prior-origin-retire-failed"))
        }
        if (confirmRetire) AlertDialog(
            onDismissRequest = { confirmRetire = false },
            confirmButton = {
                TextButton(
                    { confirmRetire = false; actions.onRetirePriorOrigin() },
                    Modifier.testTag("occurrence-payment-prior-origin-retire-confirm"),
                ) { Text(stringResource(R.string.recurring_payment_retire_prior_origin)) }
            },
            dismissButton = { TextButton({ confirmRetire = false }) { Text(stringResource(R.string.occurrence_keep)) } },
            text = { Text(stringResource(R.string.recurring_payment_retire_prior_confirm)) },
        )
    }
    if (!origin.localDraftHeld) return
    Text(
        stringResource(R.string.recurring_payment_local_draft_held),
        modifier = Modifier.testTag("occurrence-payment-local-draft"),
    )
    if (!origin.priorGenerationOccupied) {
        TextButton(
            onClick = actions.onOpenOrigin,
            modifier = Modifier.testTag("occurrence-payment-local-draft-view"),
        ) { Text(stringResource(R.string.recurring_payment_local_draft_view_origin)) }
    }
    TextButton(
        onClick = actions.onContinueLocalDraft,
        modifier = Modifier.testTag("occurrence-payment-local-draft-open"),
    ) { Text(stringResource(R.string.recurring_payment_local_draft_open)) }
    TextButton(
        onClick = actions.onAbandonLocalDraft,
        modifier = Modifier.testTag("occurrence-payment-local-draft-abandon"),
    ) { Text(stringResource(R.string.recurring_payment_local_draft_abandon)) }
}

@Composable
private fun OccurrenceRecordPayment(
    canWrite: Boolean,
    unfulfilled: Boolean,
    origin: OccurrencePaymentGuard,
    onRecord: () -> Unit,
) {
    if (!canWrite || !unfulfilled) return
    TextButton(
        onClick = onRecord,
        enabled = origin.resolved && !origin.conflict && !origin.localDraftHeld &&
            !origin.priorGenerationOccupied,
        modifier = Modifier.testTag("occurrence-record-payment"),
    ) { Text(stringResource(R.string.occurrence_record_payment)) }
}

@Composable
private fun OccurrencePeriodControls(state: RecurringOccurrenceUiState, actions: OccurrenceSheetActions) {
    var period by rememberSaveable(state.item?.publicId, state.occurrence?.period) { mutableStateOf(state.occurrence?.period.orEmpty()) }
    AppTextInput(state = AppTextInputState(label = stringResource(R.string.occurrence_period), value = period,
        placeholder = stringResource(R.string.occurrence_period_placeholder)),
        actions = AppTextInputActions(onValueChange = { period = it }), modifier = Modifier.fillMaxWidth().testTag("occurrence-period"))
    FlowRow(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        TextButton(onClick = { actions.onPeriod(period) }, enabled = !state.loading && !state.saving) { Text(stringResource(R.string.occurrence_show_period)) }
        TextButton(onClick = actions.onRefresh, enabled = !state.loading && !state.saving) { Text(stringResource(R.string.occurrence_refresh)) }
    }
    if (state.loading) Text(stringResource(R.string.occurrence_loading))
}

private fun occurrenceChoiceActions(
    state: RecurringOccurrenceUiState,
    actions: OccurrenceSheetActions,
): (@Composable ColumnScope.() -> Unit)? {
    val occurrence = state.occurrence ?: return null
    val choice = state.choice
    if (choice == null) {
        val expenseId = occurrence.expenseId ?: return null
        return {
            AppPrimaryButton(text = stringResource(R.string.occurrence_open_payment),
                onClick = { actions.onOpenExpense(expenseId) }, enabled = !state.saving, modifier = Modifier.fillMaxWidth())
        }
    }
    return {
        val label = if (choice.request.action == "clear") stringResource(R.string.occurrence_clear_review)
            else stringResource(R.string.occurrence_link_review, choice.paymentLabel.orEmpty(),
                occurrencePaymentAmountText(choice.paymentAmountCents, choice.paymentCurrencyCode))
        Text(label)
        AppPrimaryButton(text = stringResource(R.string.occurrence_submit), icons = AppButtonIcons(leading = Icons.Filled.Check), onClick = actions.onSubmit,
            enabled = state.canWrite, modifier = Modifier.fillMaxWidth().testTag("occurrence-submit"))
    }
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
    var filtersExpanded by rememberSaveable(state.item?.publicId, state.occurrence?.period) { mutableStateOf(false) }
    val payments = occurrencePaymentChoices(state.payments, month, query, preferredExpenseId)
    HorizontalDivider()
    Text(stringResource(R.string.occurrence_pick_title), style = MaterialTheme.typography.titleMedium)
    val scope = listOf(month.ifBlank { stringResource(R.string.occurrence_all_payment_months) }, query)
        .filter { it.isNotBlank() }.joinToString(" · ")
    TextButton(onClick = { filtersExpanded = !filtersExpanded }, modifier = Modifier.testTag("occurrence-payment-filter-toggle")) {
        Text(stringResource(if (filtersExpanded) R.string.occurrence_filters_hide else R.string.occurrence_filters_show, scope))
    }
    if (filtersExpanded) {
        AppTextInput(state = AppTextInputState(label = stringResource(R.string.occurrence_payment_month), value = month,
            placeholder = stringResource(R.string.occurrence_payment_month_placeholder)),
            actions = AppTextInputActions(onValueChange = { month = it }), modifier = Modifier.fillMaxWidth())
        AppTextInput(state = AppTextInputState(label = stringResource(R.string.occurrence_search), value = query),
            actions = AppTextInputActions(onValueChange = { query = it }), modifier = Modifier.fillMaxWidth())
    }
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    if (payments.isEmpty()) Text(stringResource(R.string.occurrence_no_payments), style = MaterialTheme.typography.bodyMedium, color = muted)
    if (payments.size > 20) Text(stringResource(R.string.occurrence_narrow_search), style = MaterialTheme.typography.bodySmall, color = muted)
    payments.take(20).forEachIndexed { index, payment ->
        OccurrencePaymentRow(payment, showDivider = index < minOf(payments.size, 20) - 1) { choose(payment) }
    }
    Text(stringResource(R.string.occurrence_pick_explanation), style = MaterialTheme.typography.bodySmall, color = muted)
}

/** One confirmed bill offered as this period's payment: who, how much, and the day it was booked. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun OccurrencePaymentRow(payment: ConfirmedStreamItem.ExpenseRow, showDivider: Boolean, onChoose: () -> Unit) {
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    AppListRow(modifier = Modifier.fillMaxWidth().testTag("occurrence-payment-" + payment.root.id), onClick = onChoose,
        showDivider = showDivider) {
        SettingsEntryIcon(Icons.Outlined.ReceiptLong, modifier = Modifier.padding(end = AppSpacing.compactGap))
        Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
            FlowRow(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween,
                verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
                Text(payment.root.merchant.orEmpty(), modifier = Modifier.padding(end = AppSpacing.contentGap),
                    style = MaterialTheme.typography.titleSmall)
                Text(occurrencePaymentAmountText(payment.root.amountCents, payment.root.homeCurrencyCode),
                    style = MaterialTheme.typography.titleSmall.tabularNum())
            }
            Text(payment.streamDate?.let(::displayCalendarDay) ?: stringResource(R.string.calendar_date_pending),
                style = MaterialTheme.typography.bodySmall, color = muted)
            if (payment.lineageStatus != ExpenseLineageStatus.Confirmed) {
                Text(stringResource(R.string.occurrence_has_refund), style = MaterialTheme.typography.bodySmall, color = muted)
            }
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
                it.root.amountCents?.let { amount -> amount >= 0 } == true && it.lineageStatus != ExpenseLineageStatus.Reversed
        }
    val preferred = eligible.filter { it.root.id == preferredExpenseId }
    val ordinary = filterConfirmedStreamItems(eligible, ExpenseFilterCriteria(month = month, query = query))
        .filterIsInstance<ConfirmedStreamItem.ExpenseRow>().filter {
            it.root.id != preferredExpenseId
        }.sortedByDescending { it.streamDate }
    return preferred + ordinary
}

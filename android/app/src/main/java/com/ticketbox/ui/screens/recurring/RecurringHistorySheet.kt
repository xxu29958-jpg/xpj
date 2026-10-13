package com.ticketbox.ui.screens.recurring

import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.remote.dto.RecurringDefinitionDto
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.*
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.RecurringHistoryState

@Composable
internal fun RecurringHistorySheet(state: RecurringHistoryState, retry: () -> Unit, more: () -> Unit, dismiss: () -> Unit) {
    AppBusyGuardedSheet(isSubmitting = false, onDismiss = dismiss, skipPartiallyExpanded = true) {
        AppSheetScaffold(title = stringResource(R.string.recurring_history_title), subtitle = state.merchant,
            modifier = Modifier.fillMaxHeight()) {
            AppHistoryScope(state.items.map { it.rowVersion }, state.nextBeforeVersion != null, state.fromCache, state.fetchedAt)
            state.items.forEachIndexed { index, entry ->
                val before = state.items.getOrNull(index + 1)?.takeIf {
                    it.rowVersion == entry.rowVersion - 1 && entry.changeKind !in listOf("baseline", "create")
                }?.snapshot
                AppHistoryRecord(
                    title = stringResource(R.string.recurring_history_version, entry.rowVersion,
                        stringResource(recurringHistoryKind(entry.changeKind))),
                    recordedAt = stringResource(R.string.recurring_history_saved_at, displayDateTime(entry.recordedAt)),
                    summary = {
                        Text(entry.snapshot.merchant, style = MaterialTheme.typography.titleMedium)
                        AppHistoryComparison(stringResource(R.string.recurring_form_amount_label),
                            before?.let { historyRecordedAmount(it.baselineAmountCents, it.homeCurrencyCode) },
                            historyRecordedAmount(entry.snapshot.baselineAmountCents, entry.snapshot.homeCurrencyCode))
                        AppHistoryBoundary(entry.changeKind, before == null)
                    },
                ) {
                    if (before != null) RecurringHistoryChanges(before, entry.snapshot)
                    RecurringDefinitionContent(entry.snapshot)
                }
            }
            if (state.loading) Text(stringResource(R.string.budget_history_loading))
            state.error?.let {
                Text(it.asString())
                if (state.items.isNotEmpty()) Text(stringResource(R.string.recurring_history_read_pages))
                TextButton(onClick = retry) { Text(stringResource(R.string.common_retry)) }
            }
            if (!state.loading && state.error == null && state.items.isEmpty()) Text(stringResource(R.string.recurring_history_empty))
            if (state.error == null && state.nextBeforeVersion != null) {
                TextButton(onClick = more, enabled = !state.loading) { Text(stringResource(R.string.budget_history_more)) }
            }
            Text(stringResource(R.string.recurring_history_explanation), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun RecurringHistoryChanges(before: RecurringDefinitionDto, after: RecurringDefinitionDto) {
    if (before.merchant != after.merchant) AppHistoryField(stringResource(R.string.plan_history_name), before.merchant, after.merchant)
    if (before.nextExpectedDate != after.nextExpectedDate) AppHistoryField(stringResource(R.string.plan_history_schedule),
        before.nextExpectedDate?.let(::recurringDisplayDate) ?: stringResource(R.string.occurrence_no_reminder),
        after.nextExpectedDate?.let(::recurringDisplayDate) ?: stringResource(R.string.occurrence_no_reminder))
    if (before.status != after.status) AppHistoryField(stringResource(R.string.plan_history_status),
        recurringHistoryStatus(before.status), recurringHistoryStatus(after.status))
}

@Composable
private fun recurringHistoryStatus(status: String): String = stringResource(when (status) {
    "paused" -> R.string.recurring_status_paused
    "archived" -> R.string.recurring_status_archived
    else -> R.string.recurring_status_active
})

@Composable
internal fun RecurringDefinitionContent(plan: RecurringDefinitionDto) {
    Text(plan.merchant, style = MaterialTheme.typography.titleMedium)
    Text(stringResource(R.string.recurring_history_monthly_amount,
        recurringRecordedAmountText(plan.baselineAmountCents, plan.homeCurrencyCode)),
        style = MaterialTheme.typography.titleMedium.tabularNum())
    Text(stringResource(R.string.recurring_history_anchor,
        plan.nextExpectedDate?.let(::recurringDisplayDate) ?: stringResource(R.string.occurrence_no_reminder)))
    Text(stringResource(when (plan.status) {
        "paused" -> R.string.recurring_status_paused
        "archived" -> R.string.recurring_status_archived
        else -> R.string.recurring_status_active
    }))
    Text(when (plan.source) {
        "manual" -> stringResource(R.string.recurring_history_manual)
        "candidate" -> stringResource(R.string.recurring_history_candidate)
        else -> stringResource(R.string.recurring_history_source, plan.source)
    })
}

private fun recurringHistoryKind(kind: String): Int = when (kind) {
    "baseline" -> R.string.budget_history_baseline
    "create" -> R.string.recurring_history_create
    "edit" -> R.string.recurring_history_edit
    "pause" -> R.string.recurring_action_pause_description
    "resume" -> R.string.recurring_action_resume_description
    "archive" -> R.string.budget_history_archive
    "restore" -> R.string.budget_history_restore
    else -> R.string.recurring_history_title
}

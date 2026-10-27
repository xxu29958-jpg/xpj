package com.ticketbox.ui.screens

import com.ticketbox.presentation.displayDateTime
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.IncomeDefinition
import com.ticketbox.domain.model.IncomeRevision
import com.ticketbox.domain.model.IncomeSourceType
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.*
import com.ticketbox.viewmodel.IncomeHistoryState

@Composable
internal fun IncomeHistorySheet(state: IncomeHistoryState, onRetry: () -> Unit, onMore: () -> Unit, onDismiss: () -> Unit) {
    AppBusyGuardedSheet(isSubmitting = false, onDismiss = onDismiss, skipPartiallyExpanded = true) {
        AppSheetScaffold(title = stringResource(R.string.income_history_title), modifier = Modifier.fillMaxHeight()) {
            AppHistoryScope(state.items.map { it.rowVersion }, state.nextBeforeVersion != null, state.fromCache, state.fetchedAt)
            state.items.forEachIndexed { index, entry ->
                IncomeHistoryEntry(entry, state.items.getOrNull(index + 1)?.takeIf {
                    it.rowVersion == entry.rowVersion - 1 && entry.changeKind !in listOf("baseline", "create")
                })
            }
            if (state.loading) Text(stringResource(R.string.budget_history_loading))
            state.error?.let {
                Text(it.asString())
                TextButton(onClick = onRetry) { Text(stringResource(R.string.common_retry)) }
            }
            if (!state.loading && state.error == null && state.items.isEmpty()) Text(stringResource(R.string.income_history_empty))
            if (state.error == null && state.nextBeforeVersion != null) {
                TextButton(onClick = onMore, enabled = !state.loading) { Text(stringResource(R.string.budget_history_more)) }
            }
            Text(stringResource(R.string.income_history_explanation), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
internal fun IncomeReadSource(fetchedAt: String?, fromCache: Boolean) {
    if (fetchedAt == null) return
    Text(stringResource(if (fromCache) R.string.income_read_cached else R.string.income_read_fresh,
        displayDateTime(fetchedAt)), style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant)
}

@Composable
private fun IncomeHistoryEntry(entry: IncomeRevision, previous: IncomeRevision?) {
    val saved = entry.snapshot
    val before = previous?.snapshot
    AppHistoryRecord(
        title = stringResource(R.string.goal_history_version, entry.rowVersion, stringResource(incomeHistoryKindLabel(entry.changeKind))),
        recordedAt = stringResource(R.string.goal_history_recorded_at, displayDateTime(entry.recordedAt)),
        summary = {
            Text(saved.label, style = MaterialTheme.typography.titleMedium)
            AppHistoryComparison(stringResource(R.string.income_plan_sheet_label_amount_one_time),
                before?.let { historyRecordedAmount(it.amountCents, it.homeCurrencyCode) },
                historyRecordedAmount(saved.amountCents, saved.homeCurrencyCode))
            AppHistoryBoundary(entry.changeKind, previous == null)
        },
    ) {
        AppHistoryField(stringResource(R.string.plan_history_name), before?.label, saved.label)
        AppHistoryField(stringResource(R.string.plan_history_source), before?.let { incomeHistorySource(it.sourceType) },
            incomeHistorySource(saved.sourceType))
        AppHistoryField(stringResource(R.string.plan_history_schedule), before?.let { incomeHistorySchedule(it) }, incomeHistorySchedule(saved))
        Text(stringResource(R.string.income_history_months, entry.intentMonth?.let { displayMonthLabel(it) } ?: stringResource(R.string.income_history_unknown),
            entry.effectiveMonth?.let { displayMonthLabel(it) } ?: stringResource(R.string.income_history_unknown)))
        AppHistoryField(stringResource(R.string.plan_history_status), before?.let { incomeHistoryStatus(it.status) }, incomeHistoryStatus(saved.status))
    }
}

@Composable
private fun incomeHistorySchedule(saved: IncomeDefinition): String =
    if (saved.frequency == "one_time") stringResource(R.string.income_history_one_time,
        displayMonthLabel(saved.incomeMonth.orEmpty()), saved.payDay) else stringResource(R.string.income_history_monthly, saved.payDay)

@Composable
private fun incomeHistorySource(value: String): String = IncomeSourceType.entries.firstOrNull { it.wireValue == value }
    ?.let { stringResource(incomeSourceTypeLabelRes(it)) } ?: value

@Composable
private fun incomeHistoryStatus(value: String): String =
    stringResource(if (value == "archived") R.string.income_plan_section_archived else R.string.income_plan_section_active)

private fun incomeHistoryKindLabel(kind: String): Int = when (kind) {
        "baseline" -> R.string.budget_history_baseline
        "create" -> R.string.income_history_create
        "edit" -> R.string.income_history_edit
        "archive" -> R.string.income_history_archive
        "restore" -> R.string.income_history_restore
        else -> R.string.income_history_title
    }

package com.ticketbox.ui.screens.budget

import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.BudgetRevision
import com.ticketbox.ui.components.*
import com.ticketbox.viewmodel.BudgetHistoryState

@Composable
fun BudgetHistorySheet(state: BudgetHistoryState, onRetry: () -> Unit, onMore: () -> Unit, onDismiss: () -> Unit) {
    AppBusyGuardedSheet(isSubmitting = false, onDismiss = onDismiss, skipPartiallyExpanded = true) {
        AppSheetScaffold(title = stringResource(R.string.budget_history_title), subtitle = displayMonthLabel(state.month),
            modifier = Modifier.fillMaxHeight().testTag("budget-history")) {
            AppHistoryScope(state.items.map { it.rowVersion }, state.nextBeforeVersion != null, state.fromCache, state.fetchedAt,
                readSourceModifier = Modifier.testTag("budget-history-read-source"))
            state.items.forEachIndexed { index, entry ->
                val previous = state.items.getOrNull(index + 1)?.takeIf {
                    it.rowVersion == entry.rowVersion - 1 && entry.changeKind !in listOf("baseline", "create")
                }
                BudgetHistoryEntry(entry, previous)
            }
            if (state.loading) Text(stringResource(R.string.budget_history_loading))
            if (state.failed) {
                Text(stringResource(R.string.budget_history_failed))
                TextButton(onClick = onRetry) { Text(stringResource(R.string.budget_history_retry)) }
            } else if (!state.loading && state.items.isEmpty()) {
                Text(stringResource(R.string.budget_history_empty))
            }
            if (!state.failed && state.nextBeforeVersion != null) {
                TextButton(onClick = onMore, enabled = !state.loading) {
                    Text(stringResource(R.string.budget_history_more))
                }
            }
            Text(stringResource(R.string.budget_history_explanation), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun BudgetHistoryEntry(entry: BudgetRevision, previous: BudgetRevision?) {
    val snapshot = entry.snapshot
    val before = previous?.snapshot
    AppHistoryRecord(title = stringResource(R.string.goal_history_version, entry.rowVersion, stringResource(historyTitle(entry.changeKind))),
        recordedAt = displayDateTime(entry.recordedAt), summary = {
            AppHistoryComparison(stringResource(R.string.budget_editor_total_label),
                before?.let { historyRecordedAmount(it.totalAmountCents, it.homeCurrencyCode) },
                historyRecordedAmount(snapshot.totalAmountCents, snapshot.homeCurrencyCode))
            AppHistoryBoundary(entry.changeKind, previous == null)
        }) {
        AppHistoryField(stringResource(R.string.plan_history_status), before?.let { budgetHistoryStatus(it.archived) },
            budgetHistoryStatus(snapshot.archived))
        AppHistoryField(stringResource(R.string.budget_editor_rollover_label),
            before?.let { historyRecordedAmount(it.rolloverAmountCents, it.homeCurrencyCode) },
            historyRecordedAmount(snapshot.rolloverAmountCents, snapshot.homeCurrencyCode))
        AppHistoryField(stringResource(R.string.budget_editor_non_monthly_label),
            before?.let { historyRecordedAmount(it.nonMonthlyAmountCents, it.homeCurrencyCode) },
            historyRecordedAmount(snapshot.nonMonthlyAmountCents, snapshot.homeCurrencyCode))
        val none = stringResource(R.string.budget_history_none)
        AppHistoryField(stringResource(R.string.plan_history_excluded), before?.excludedCategories?.joinToString("、")?.ifEmpty { none },
            snapshot.excludedCategories.joinToString("、").ifEmpty { none })
        val categories = (snapshot.categoryBudgets.map { it.category } + before?.categoryBudgets.orEmpty().map { it.category }).distinct()
        if (categories.isEmpty()) Text(stringResource(R.string.budget_history_no_categories))
        categories.forEach { category ->
            val oldAmount = before?.categoryBudgets?.firstOrNull { it.category == category }?.amountCents
            val amount = snapshot.categoryBudgets.firstOrNull { it.category == category }?.amountCents
            val notSet = stringResource(R.string.plan_history_not_set)
            AppHistoryField(category, before?.let { oldAmount?.let { historyRecordedAmount(it, before.homeCurrencyCode) } ?: notSet },
                amount?.let { historyRecordedAmount(it, snapshot.homeCurrencyCode) } ?: notSet)
        }
    }
}

@Composable
private fun budgetHistoryStatus(archived: Boolean): String =
    stringResource(if (archived) R.string.budget_history_archived else R.string.goal_history_active)

private fun historyTitle(kind: String): Int = when (kind) {
    "baseline" -> R.string.budget_history_baseline
    "create" -> R.string.budget_history_create
    "edit" -> R.string.budget_history_edit
    "archive" -> R.string.budget_history_archive
    "restore" -> R.string.budget_history_restore
    else -> R.string.budget_history_title
}

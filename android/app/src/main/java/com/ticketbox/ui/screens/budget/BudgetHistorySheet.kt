package com.ticketbox.ui.screens.budget

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.BudgetRevision
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.AppBusyGuardedSheet
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.BudgetHistoryState

@Composable
fun BudgetHistorySheet(state: BudgetHistoryState, onRetry: () -> Unit, onMore: () -> Unit, onDismiss: () -> Unit) {
    AppBusyGuardedSheet(isSubmitting = false, onDismiss = onDismiss, skipPartiallyExpanded = true) {
        AppSheetScaffold(title = stringResource(R.string.budget_history_title), subtitle = state.month) {
            Text(stringResource(R.string.budget_history_explanation))
            state.items.forEach { entry -> BudgetHistoryEntry(entry) }
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
        }
    }
}

@Composable
private fun BudgetHistoryEntry(entry: BudgetRevision) {
    val snapshot = entry.snapshot
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        HorizontalDivider()
        Text(stringResource(historyTitle(entry.changeKind)), style = MaterialTheme.typography.titleMedium)
        Text(displayDateTime(entry.recordedAt), style = MaterialTheme.typography.bodySmall)
        if (entry.changeKind == "baseline") Text(stringResource(R.string.budget_history_baseline_note))
        if (snapshot.archived) Text(stringResource(R.string.budget_history_archived))
        Text(stringResource(R.string.budget_history_total, historyAmount(snapshot.totalAmountCents, snapshot.homeCurrencyCode)))
        Text(stringResource(R.string.budget_history_rollover, historyAmount(snapshot.rolloverAmountCents, snapshot.homeCurrencyCode)))
        Text(stringResource(R.string.budget_history_reserved, historyAmount(snapshot.nonMonthlyAmountCents, snapshot.homeCurrencyCode)))
        Text(stringResource(R.string.budget_history_excluded, snapshot.excludedCategories.joinToString("、")
            .ifEmpty { stringResource(R.string.budget_history_none) }))
        if (snapshot.categoryBudgets.isEmpty()) Text(stringResource(R.string.budget_history_no_categories))
        snapshot.categoryBudgets.forEach {
            Text(stringResource(R.string.budget_history_category, it.category, historyAmount(it.amountCents, snapshot.homeCurrencyCode)))
        }
    }
}

@Composable
private fun historyAmount(amount: Long, currency: String?): String =
    if (currency == null) stringResource(R.string.budget_history_unknown_money, amount.toString())
    else formatDisplayAmount(amount, CurrencyDisplay.forRecord(currency))

private fun historyTitle(kind: String): Int = when (kind) {
    "baseline" -> R.string.budget_history_baseline
    "create" -> R.string.budget_history_create
    "edit" -> R.string.budget_history_edit
    "archive" -> R.string.budget_history_archive
    "restore" -> R.string.budget_history_restore
    else -> R.string.budget_history_title
}

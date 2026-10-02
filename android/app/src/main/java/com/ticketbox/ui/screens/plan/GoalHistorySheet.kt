package com.ticketbox.ui.screens.plan

import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.GoalRevision
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppBusyGuardedSheet
import com.ticketbox.ui.components.AppHistoryRecord
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.GoalHistoryState

@Composable
internal fun GoalHistorySheet(state: GoalHistoryState, onRetry: () -> Unit, onMore: () -> Unit, onDismiss: () -> Unit) {
    AppBusyGuardedSheet(isSubmitting = false, onDismiss = onDismiss, skipPartiallyExpanded = true) {
        AppSheetScaffold(title = stringResource(R.string.goal_history_title), modifier = Modifier.fillMaxHeight()) {
            Text(stringResource(R.string.goal_history_explanation))
            if (state.fromCache) Text(stringResource(R.string.goal_history_offline, displayDateTime(state.fetchedAt)))
            state.items.forEach { GoalHistoryEntry(it) }
            if (state.loading) Text(stringResource(R.string.budget_history_loading))
            state.error?.let {
                Text(it.asString())
                TextButton(onClick = onRetry) { Text(stringResource(R.string.common_retry)) }
            }
            if (!state.loading && state.error == null && state.items.isEmpty()) {
                Text(stringResource(R.string.goal_history_empty))
            }
            if (state.error == null && state.nextBeforeVersion != null) {
                TextButton(onClick = onMore, enabled = !state.loading) { Text(stringResource(R.string.budget_history_more)) }
            }
        }
    }
}

@Composable
private fun GoalHistoryEntry(entry: GoalRevision) {
    val plan = entry.snapshot
    AppHistoryRecord(
        title = stringResource(R.string.goal_history_version, entry.rowVersion, stringResource(historyKind(entry.changeKind))),
        recordedAt = stringResource(R.string.goal_history_recorded_at, displayDateTime(entry.recordedAt)),
    ) {
        Text(plan.name, style = MaterialTheme.typography.titleMedium)
        Text(if (plan.homeCurrencyCode == null) stringResource(R.string.budget_history_unknown_money,
            plan.targetAmountCents.toString()) else formatDisplayAmount(plan.targetAmountCents,
            CurrencyDisplay.forRecord(plan.homeCurrencyCode)), style = MaterialTheme.typography.titleMedium.tabularNum())
        plan.homeCurrencyCode?.let { Text(it, style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant) }
        if (entry.changeKind == "baseline") Text(stringResource(R.string.budget_history_baseline_note))
        Text(stringResource(R.string.spending_goal_detail_subtitle, displayMonthLabel(plan.month.orEmpty()),
            plan.category ?: stringResource(R.string.spending_goal_scope_all)))
        Text(stringResource(if (plan.status == "archived") R.string.goal_history_archived else R.string.goal_history_active))
    }
}

private fun historyKind(kind: String): Int = when (kind) {
    "baseline" -> R.string.budget_history_baseline
    "create" -> R.string.goal_history_create
    "edit" -> R.string.goal_history_edit
    "archive" -> R.string.goal_history_archive
    "restore" -> R.string.goal_history_restore
    else -> R.string.goal_history_title
}

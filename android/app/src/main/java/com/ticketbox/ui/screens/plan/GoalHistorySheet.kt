package com.ticketbox.ui.screens.plan

import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.GoalDefinition
import com.ticketbox.domain.model.GoalRevision
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.*
import com.ticketbox.viewmodel.GoalHistoryState

@Composable
internal fun GoalHistorySheet(state: GoalHistoryState, onRetry: () -> Unit, onMore: () -> Unit, onDismiss: () -> Unit) {
    AppBusyGuardedSheet(isSubmitting = false, onDismiss = onDismiss, skipPartiallyExpanded = true) {
        AppSheetScaffold(title = stringResource(R.string.goal_history_title), modifier = Modifier.fillMaxHeight()) {
            AppHistoryScope(state.items.map { it.rowVersion }, state.nextBeforeVersion != null, state.fromCache, state.fetchedAt)
            state.items.forEachIndexed { index, entry ->
                GoalHistoryEntry(entry, state.items.getOrNull(index + 1)?.takeIf {
                    it.rowVersion == entry.rowVersion - 1 && entry.changeKind !in listOf("baseline", "create")
                })
            }
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
            Text(stringResource(R.string.goal_history_explanation), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun GoalHistoryEntry(entry: GoalRevision, previous: GoalRevision?) {
    val plan = entry.snapshot
    val before = previous?.snapshot
    AppHistoryRecord(
        title = stringResource(R.string.goal_history_version, entry.rowVersion, stringResource(historyKind(entry.changeKind))),
        recordedAt = stringResource(R.string.goal_history_recorded_at, displayDateTime(entry.recordedAt)),
        summary = {
            Text(plan.name, style = MaterialTheme.typography.titleMedium)
            AppHistoryComparison(stringResource(R.string.spending_goal_create_amount_label),
                before?.let { historyRecordedAmount(it.targetAmountCents, it.homeCurrencyCode) },
                historyRecordedAmount(plan.targetAmountCents, plan.homeCurrencyCode))
            AppHistoryBoundary(entry.changeKind, previous == null)
        },
    ) {
        AppHistoryField(stringResource(R.string.plan_history_name), before?.name, plan.name)
        AppHistoryField(stringResource(R.string.plan_history_scope), before?.let { goalHistoryScope(it) }, goalHistoryScope(plan))
        AppHistoryField(stringResource(R.string.plan_history_status), before?.let { goalHistoryStatus(it.status) }, goalHistoryStatus(plan.status))
    }
}

@Composable
private fun goalHistoryScope(plan: GoalDefinition): String = stringResource(R.string.spending_goal_detail_subtitle,
    displayMonthLabel(plan.month.orEmpty()), plan.category ?: stringResource(R.string.spending_goal_scope_all))

@Composable
private fun goalHistoryStatus(value: String): String =
    stringResource(if (value == "archived") R.string.goal_history_archived else R.string.goal_history_active)

private fun historyKind(kind: String): Int = when (kind) {
    "baseline" -> R.string.budget_history_baseline
    "create" -> R.string.goal_history_create
    "edit" -> R.string.goal_history_edit
    "archive" -> R.string.goal_history_archive
    "restore" -> R.string.goal_history_restore
    else -> R.string.goal_history_title
}

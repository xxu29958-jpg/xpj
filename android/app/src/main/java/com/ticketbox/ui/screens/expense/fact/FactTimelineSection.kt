package com.ticketbox.ui.screens.expense.fact

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.asString
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.ExpenseDetailDataLoadState
import com.ticketbox.viewmodel.ExpenseFactUiState
import com.ticketbox.viewmodel.FactTimelineEntry
import com.ticketbox.viewmodel.toTimelineEntries

private const val TIMELINE_PREVIEW_COUNT = 3

/**
 * A1 变更记录时间线：newest-first 人话 delta（kind pill + reason 加粗 +
 * 时间·操作者 meta），默认最新 3 条 + 「查看全部 N 条」展开；系统字段已由
 * mapper 折叠。失败态可点按重试，空态诚实说明。
 */
@Composable
internal fun FactTimelineSection(
    state: ExpenseFactUiState,
    onRetryLoad: () -> Unit,
    onToggleExpanded: () -> Unit,
) {
    val expense = state.expense ?: return
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        AppSectionHeader(title = stringResource(R.string.expense_fact_timeline_title))
        when (state.revisionsLoadState) {
            ExpenseDetailDataLoadState.Failed -> {
                TextButton(onClick = onRetryLoad) {
                    Text(text = stringResource(R.string.expense_fact_revisions_failed))
                }
            }
            ExpenseDetailDataLoadState.Loaded -> {
                if (state.revisions.isEmpty()) {
                    Text(
                        text = stringResource(R.string.expense_fact_timeline_empty),
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        style = MaterialTheme.typography.bodySmall,
                    )
                } else {
                    val entries = remember(state.revisions, expense) {
                        state.revisions.toTimelineEntries(expense.homeCurrency)
                    }
                    val visible = if (state.timelineExpanded) entries else entries.take(TIMELINE_PREVIEW_COUNT)
                    visible.forEach { entry ->
                        FactTimelineEntryRow(entry = entry)
                    }
                    if (state.revisionsTotal > TIMELINE_PREVIEW_COUNT || entries.size > TIMELINE_PREVIEW_COUNT) {
                        QuietOutlinedButton(
                            text = if (state.timelineExpanded) {
                                stringResource(R.string.expense_fact_timeline_collapse)
                            } else {
                                stringResource(R.string.expense_fact_timeline_expand, state.revisionsTotal)
                            },
                            onClick = onToggleExpanded,
                        )
                    }
                }
            }
            else -> {
                Text(
                    text = stringResource(R.string.expense_fact_timeline_title) + "…",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
    }
}

@Composable
private fun FactTimelineEntryRow(entry: FactTimelineEntry) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        Row(
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            StatusPill(
                text = stringResource(entry.kindLabelRes),
                active = !entry.isCorrection,
            )
            Text(
                text = entry.whenText,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodySmall,
            )
            if (entry.actor.isNotBlank()) {
                Text(
                    text = entry.actor,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
        }
        Text(
            text = entry.reason,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleSmall,
        )
        entry.changes.forEach { change ->
            val before = change.before.asString()
            val after = change.after.asString()
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
            ) {
                Text(
                    text = change.label.asString(),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.fillMaxWidth(0.28f),
                )
                Text(
                    text = if (before.isNotEmpty()) "$before → $after" else after,
                    color = MaterialTheme.colorScheme.onSurface,
                    style = MaterialTheme.typography.bodySmall,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
        }
    }
}

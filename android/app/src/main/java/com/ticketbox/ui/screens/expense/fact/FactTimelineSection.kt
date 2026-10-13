package com.ticketbox.ui.screens.expense.fact

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.annotation.StringRes
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.AppAdaptiveContentActionRow
import com.ticketbox.ui.components.AppAdaptiveContentActionStyle
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.asString
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.ExpenseDetailDataLoadState
import com.ticketbox.viewmodel.ExpenseFactUiState
import com.ticketbox.viewmodel.FactTimelineCollectionDetail
import com.ticketbox.viewmodel.FactTimelineCollectionRow
import com.ticketbox.viewmodel.FactTimelineEntry
import com.ticketbox.viewmodel.toTimelineEntries

private const val TIMELINE_PREVIEW_COUNT = 3

/**
 * A1 变更记录时间线：newest-first 人话 delta（kind pill + reason 加粗 +
 * 时间·操作者 meta），默认最新 3 条 + 「查看全部 N 条」展开；items/splits
 * 变化附完整 Before/After 集合（默认收起，只呈现 snapshot 字段，不做行级
 * diff）；服务端还有更早页时「加载更早」原地 append，失败可重试。
 * 系统字段已由 mapper 折叠。失败态可点按重试，空态诚实说明。
 */
@Composable
internal fun FactTimelineSection(
    state: ExpenseFactUiState,
    onRetryLoad: () -> Unit,
    onToggleExpanded: () -> Unit,
    onLoadOlder: () -> Unit,
) {
    val currency = state.expense?.homeCurrency ?: return
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        if (!state.timelineExpanded) AppAdaptiveContentActionRow(
            style = AppAdaptiveContentActionStyle(compactAction = true),
            content = { AppSectionHeader(title = stringResource(R.string.expense_fact_recent_changes)) },
            action = { modifier ->
                TextButton(onClick = onToggleExpanded, modifier = modifier) {
                    Text(stringResource(R.string.expense_fact_history_entry))
                }
            },
        )
        FactTimelineStateContent(state, currency, onRetryLoad, onLoadOlder)
        if (state.timelineExpanded) Text(stringResource(R.string.expense_fact_history_preserved),
            color = MaterialTheme.colorScheme.onSurfaceVariant, style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun FactTimelineStateContent(
    state: ExpenseFactUiState,
    currency: CurrencyCode,
    onRetryLoad: () -> Unit,
    onLoadOlder: () -> Unit,
) {
    when (state.revisionsLoadState) {
        ExpenseDetailDataLoadState.Failed -> TextButton(onClick = onRetryLoad) {
            Text(text = stringResource(R.string.expense_fact_revisions_failed))
        }
        ExpenseDetailDataLoadState.Loaded -> FactTimelineLoadedContent(
            state = state,
            currency = currency,
            onRetryLoad = onRetryLoad,
            onLoadOlder = onLoadOlder,
        )
        else -> Text(
            text = stringResource(R.string.expense_fact_timeline_title) + "…",
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun FactTimelineLoadedContent(
    state: ExpenseFactUiState,
    currency: CurrencyCode,
    onRetryLoad: () -> Unit,
    onLoadOlder: () -> Unit,
) {
    if (state.revisions.isEmpty()) {
        state.revisionsCachedAt?.let { at ->
            TextButton(onClick = onRetryLoad) {
                Text(stringResource(R.string.expense_fact_history_cached, com.ticketbox.ui.components.displayDateTime(at)))
            }
        }
        Text(
            text = stringResource(R.string.expense_fact_timeline_empty),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
        return
    }
    // 已有 rows 的 page1 刷新失败：staleness 警告先于被信任内容，且不抢全局 command 消息位。
    state.revisionsCachedAt?.let { at ->
        TextButton(onClick = onRetryLoad) {
            Text(stringResource(R.string.expense_fact_history_cached, com.ticketbox.ui.components.displayDateTime(at)))
        }
    }
    if (state.revisionsRefreshFailed) {
        TextButton(onClick = onRetryLoad) {
            Text(text = stringResource(R.string.expense_fact_timeline_refresh_failed))
        }
    }
    val entries = remember(state.revisions, state.revisionMemberNames, currency) {
        state.revisions.toTimelineEntries(currency, state.revisionMemberNames)
    }
    val visible = if (state.timelineExpanded) entries else entries.take(TIMELINE_PREVIEW_COUNT)
    visible.forEach { entry -> FactTimelineEntryRow(entry = entry) }
    FactTimelineOlderAction(state = state, onLoadOlder = onLoadOlder)
}

@Composable
private fun FactTimelineOlderAction(
    state: ExpenseFactUiState,
    onLoadOlder: () -> Unit,
) {
    if (!state.timelineExpanded || state.revisionsNextPage == null) return
    if (state.revisionsOlderLoadFailed) {
        TextButton(
            enabled = !state.revisionsLoading,
            onClick = onLoadOlder,
        ) {
            Text(text = stringResource(R.string.expense_fact_timeline_older_failed))
        }
        return
    }
    AppSecondaryButton(
        text = stringResource(
            R.string.expense_fact_timeline_load_older,
            (state.revisionsTotal - state.revisions.size).coerceAtLeast(0),
        ),
        enabled = !state.revisionsLoading && !state.revisionsOlderLoading,
        onClick = onLoadOlder,
    )
}

@Composable
private fun FactTimelineEntryRow(entry: FactTimelineEntry) {
    val line = MaterialTheme.colorScheme.outlineVariant
    val dot = MaterialTheme.colorScheme.primary
    Column(
        modifier = Modifier.fillMaxWidth().drawBehind {
            val x = AppSpacing.miniGap.toPx()
            val y = AppSpacing.smallGap.toPx()
            drawLine(line, Offset(x, y), Offset(x, size.height), strokeWidth = 1.dp.toPx())
            drawCircle(dot, radius = AppSpacing.miniGap.toPx(), center = Offset(x, y))
        }.padding(start = AppSpacing.cardPadding, bottom = AppSpacing.sectionGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        FlowRow(
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Text(
                text = stringResource(entry.kindLabelRes),
                style = MaterialTheme.typography.titleMedium,
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
        entry.summary?.let { Text(it.asString(), style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant) }
        if (entry.reason != stringResource(entry.kindLabelRes)) Text(
            text = entry.reason,
            color = MaterialTheme.colorScheme.onSurface,
            style = MaterialTheme.typography.titleSmall,
        )
        FactTimelineChanges(entry.changes)
        entry.collections.forEach { collection ->
            FactTimelineCollectionDisclosure(collection = collection)
        }
    }
}

@Composable
private fun FactTimelineChanges(changes: List<com.ticketbox.viewmodel.FactTimelineChange>) {
    changes.forEach { change ->
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

/** 完整 Before/After 集合的原地展开件：默认收起；CTA 前缀字段标签，
 *  避免同一条目 items+splits 双 disclosure 出现两个无差别按钮（读屏可达性）。 */
@Composable
private fun FactTimelineCollectionDisclosure(collection: FactTimelineCollectionDetail) {
    var expanded by remember { mutableStateOf(false) }
    TextButton(onClick = { expanded = !expanded }) {
        Text(
            text = stringResource(
                if (expanded) {
                    R.string.expense_fact_timeline_detail_collapse_for
                } else {
                    R.string.expense_fact_timeline_detail_expand_for
                },
                stringResource(collection.labelRes),
            ),
        )
    }
    if (expanded) {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap)) {
            FactTimelineCollectionSet(
                labelRes = R.string.expense_fact_timeline_before_label,
                rows = collection.beforeRows,
            )
            FactTimelineCollectionSet(
                labelRes = R.string.expense_fact_timeline_after_label,
                rows = collection.afterRows,
            )
        }
    }
}

@Composable
private fun FactTimelineCollectionSet(
    @StringRes labelRes: Int,
    rows: List<FactTimelineCollectionRow>,
) {
    Text(
        text = stringResource(labelRes),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodySmall,
    )
    if (rows.isEmpty()) {
        Text(
            text = stringResource(R.string.expense_fact_timeline_value_empty),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
    rows.forEach { row ->
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.cardPaddingTight),
        ) {
            Text(
                text = row.title.asString(),
                color = MaterialTheme.colorScheme.onSurface,
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis,
                modifier = Modifier.weight(1f),
            )
            if (row.facts.isNotEmpty()) {
                val factTexts = buildList { row.facts.forEach { add(it.asString()) } }
                Text(
                    text = factTexts.joinToString(" · "),
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodySmall.tabularNum(),
                )
            }
        }
    }
}

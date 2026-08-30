package com.ticketbox.ui.screens.expense.fact

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.annotation.StringRes
import com.ticketbox.R
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.StatusPill
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
                    // 已有 rows 的 page1 刷新失败：staleness 警告必须先于被信任的内容，
                    // 安静单行可点重试，不写全局 message（不抢 command settlement 的消息位）。
                    if (state.revisionsRefreshFailed) {
                        TextButton(onClick = onRetryLoad) {
                            Text(text = stringResource(R.string.expense_fact_timeline_refresh_failed))
                        }
                    }
                    val entries = remember(state.revisions, state.revisionMemberNames, expense) {
                        state.revisions.toTimelineEntries(expense.homeCurrency, state.revisionMemberNames)
                    }
                    val visible = if (state.timelineExpanded) entries else entries.take(TIMELINE_PREVIEW_COUNT)
                    visible.forEach { entry ->
                        FactTimelineEntryRow(entry = entry)
                    }
                    if (state.timelineExpanded && state.revisionsNextPage != null) {
                        if (state.revisionsOlderLoadFailed) {
                            TextButton(
                                enabled = !state.revisionsLoading,
                                onClick = onLoadOlder,
                            ) {
                                Text(text = stringResource(R.string.expense_fact_timeline_older_failed))
                            }
                        } else {
                            QuietOutlinedButton(
                                text = stringResource(
                                    R.string.expense_fact_timeline_load_older,
                                    (state.revisionsTotal - state.revisions.size).coerceAtLeast(0),
                                ),
                                enabled = !state.revisionsLoading && !state.revisionsOlderLoading,
                                onClick = onLoadOlder,
                            )
                        }
                    }
                    if (state.revisionsTotal > TIMELINE_PREVIEW_COUNT || entries.size > TIMELINE_PREVIEW_COUNT) {
                        QuietOutlinedButton(
                            // CTA 文案必须等于这一次点击的交付：服务端还有更早页时
                            // 只能承诺展开本地已加载的最近 M 条，不得谎称「全部 N 条」。
                            text = if (state.timelineExpanded) {
                                stringResource(R.string.expense_fact_timeline_collapse)
                            } else if (state.revisionsTotal > entries.size) {
                                stringResource(R.string.expense_fact_timeline_expand_loaded, entries.size)
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
        entry.collections.forEach { collection ->
            FactTimelineCollectionDisclosure(collection = collection)
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

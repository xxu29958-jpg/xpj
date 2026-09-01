@file:OptIn(ExperimentalFoundationApi::class)

package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.ui.screens.LedgerStreamGroup
import com.ticketbox.ui.screens.ledgerDayPreviewLabels
import com.ticketbox.viewmodel.LedgerViewMode

private object LedgerDaySectionDefaults {
    const val FoldThresholdItems = 12
    const val FoldThresholdMixedItems = 8
    const val PreviewMerchantCount = 3
}

internal data class LedgerDaySectionState(
    val viewMode: LedgerViewMode,
    val selectionMode: Boolean,
    val selectedIds: Set<Long>,
    val compactGroups: Boolean,
    val expanded: Boolean,
)

internal data class LedgerDaySectionActions(
    val onEdit: (Expense) -> Unit,
    val onEnterSelection: (Long?) -> Unit,
    val onToggleSelect: (Long) -> Unit,
    val onToggleGroup: () -> Unit,
)

internal fun shouldCompactLedgerDayGroups(groupCount: Int, itemCount: Int): Boolean {
    return itemCount > LedgerDaySectionDefaults.FoldThresholdItems ||
        (groupCount > 1 &&
            itemCount > LedgerDaySectionDefaults.FoldThresholdMixedItems)
}

internal fun LazyListScope.ledgerDaySection(
    group: LedgerStreamGroup,
    sectionState: LedgerDaySectionState,
    actions: LedgerDaySectionActions,
) {
    stickyHeader(key = "ledger-day-${group.key}") {
        LedgerDayHeader(
            state = LedgerDayHeaderUi(
                label = group.label,
                dayTotalCents = group.dayTotalCents,
                itemCount = group.itemCount,
                previewText = group.previewText().takeUnless { sectionState.expanded },
                expandable = sectionState.compactGroups,
                expanded = sectionState.expanded,
            ),
            onToggle = actions.onToggleGroup.takeIf { sectionState.compactGroups },
        )
    }
    if (sectionState.expanded) {
        // rowKey spans both id spaces: offset rows never collide with roots.
        items(group.items, key = { it.rowKey }) { item ->
            when (item) {
                is ConfirmedStreamItem.ExpenseRow -> LedgerExpenseRow(
                    state = LedgerExpenseRowState(
                        expense = item.root,
                        viewMode = sectionState.viewMode,
                        selection = LedgerExpenseSelectionState(
                            enabled = sectionState.selectionMode,
                            selected = item.root.id in sectionState.selectedIds,
                        ),
                        lineageStatus = item.lineageStatus,
                    ),
                    actions = actions,
                )
                // Offset events render as one compact event row in every view
                // mode: no checkbox, no selection long-press; a tap opens the
                // ROOT fact detail (the envelope's root, offline-openable).
                is ConfirmedStreamItem.OffsetRow -> LedgerOffsetRow(
                    state = LedgerOffsetItemState(item = item),
                    onOpen = { actions.onEdit(item.root) },
                )
            }
        }
    }
}

private data class LedgerExpenseRowState(
    val expense: Expense,
    val viewMode: LedgerViewMode,
    val selection: LedgerExpenseSelectionState,
    val lineageStatus: ExpenseLineageStatus,
)

@Composable
private fun LedgerExpenseRow(
    state: LedgerExpenseRowState,
    actions: LedgerDaySectionActions,
) {
    val expense = state.expense
    val itemState = LedgerExpenseItemState(
        expense = expense,
        selection = state.selection,
        lineageStatus = state.lineageStatus,
    )
    val itemActions = LedgerExpenseItemActions(
        onOpen = { actions.onEdit(expense) },
        onToggleSelection = { actions.onToggleSelect(expense.id) },
        onEnterSelection = { actions.onEnterSelection(expense.id) },
    )
    when (state.viewMode) {
        LedgerViewMode.Card -> LedgerExpenseCard(
            state = itemState,
            actions = itemActions,
        )
        LedgerViewMode.List -> LedgerExpenseListRow(
            state = itemState,
            actions = itemActions,
        )
        LedgerViewMode.Table -> LedgerExpenseTableRow(
            state = itemState,
            actions = itemActions,
        )
    }
}

@Composable
private fun LedgerStreamGroup.previewText(): String? {
    val separator = stringResource(R.string.ledger_day_preview_separator)
    val names = ledgerDayPreviewLabels(items, LedgerDaySectionDefaults.PreviewMerchantCount)
    if (names.isEmpty()) return null
    val hiddenCount = itemCount - names.size
    val mainText = names.joinToString(separator)
    return if (hiddenCount > 0) {
        stringResource(
            R.string.ledger_day_preview_with_more,
            mainText,
            stringResource(R.string.ledger_day_preview_more, hiddenCount),
        )
    } else {
        mainText
    }
}

@file:OptIn(ExperimentalFoundationApi::class)

package com.ticketbox.ui.screens.ledger

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.screens.LedgerExpenseGroup
import com.ticketbox.viewmodel.LedgerViewMode

private object LedgerDaySectionDefaults {
    const val FoldThresholdGroups = 4
    const val FoldThresholdItems = 18
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
    return groupCount > LedgerDaySectionDefaults.FoldThresholdGroups ||
        itemCount > LedgerDaySectionDefaults.FoldThresholdItems
}

internal fun LazyListScope.ledgerDaySection(
    group: LedgerExpenseGroup,
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
        items(group.items, key = { it.id }) { expense ->
            LedgerExpenseRow(
                state = LedgerExpenseRowState(
                    expense = expense,
                    viewMode = sectionState.viewMode,
                    selectionMode = sectionState.selectionMode,
                    selected = expense.id in sectionState.selectedIds,
                ),
                actions = actions,
            )
        }
    }
}

private data class LedgerExpenseRowState(
    val expense: Expense,
    val viewMode: LedgerViewMode,
    val selectionMode: Boolean,
    val selected: Boolean,
)

@Composable
private fun LedgerExpenseRow(
    state: LedgerExpenseRowState,
    actions: LedgerDaySectionActions,
) {
    val expense = state.expense
    val onToggle = { actions.onToggleSelect(expense.id) }
    val onLongPress = { actions.onEnterSelection(expense.id) }
    when (state.viewMode) {
        LedgerViewMode.Card -> LedgerExpenseCard(
            expense = expense,
            onEdit = { actions.onEdit(expense) },
            selectionMode = state.selectionMode,
            selected = state.selected,
            onToggleSelect = onToggle,
            onLongPress = onLongPress,
        )
        LedgerViewMode.List -> LedgerExpenseListRow(
            expense = expense,
            onEdit = { actions.onEdit(expense) },
            selectionMode = state.selectionMode,
            selected = state.selected,
            onToggleSelect = onToggle,
            onLongPress = onLongPress,
        )
        LedgerViewMode.Table -> LedgerExpenseTableRow(
            expense = expense,
            onEdit = { actions.onEdit(expense) },
            selectionMode = state.selectionMode,
            selected = state.selected,
            onToggleSelect = onToggle,
            onLongPress = onLongPress,
        )
    }
}

@Composable
private fun LedgerExpenseGroup.previewText(): String? {
    val separator = stringResource(R.string.ledger_day_preview_separator)
    val names = items
        .map { it.merchant?.trim()?.takeIf { merchant -> merchant.isNotBlank() } ?: it.category }
        .distinct()
        .take(LedgerDaySectionDefaults.PreviewMerchantCount)
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

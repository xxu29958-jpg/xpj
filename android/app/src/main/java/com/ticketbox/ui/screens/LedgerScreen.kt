package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.MonthPickerSheet
import com.ticketbox.ui.screens.ledger.EmptyLedgerState
import com.ticketbox.ui.screens.ledger.LedgerBulkEditSheet
import com.ticketbox.ui.screens.ledger.LedgerDayHeader
import com.ticketbox.ui.screens.ledger.LedgerExpenseCard
import com.ticketbox.ui.screens.ledger.LedgerExpenseListRow
import com.ticketbox.ui.screens.ledger.LedgerExpenseTableRow
import com.ticketbox.ui.screens.ledger.LedgerFilterPanel
import com.ticketbox.ui.screens.ledger.LedgerSelectionBar
import com.ticketbox.ui.screens.ledger.LedgerToolsSheet
import com.ticketbox.viewmodel.LedgerUiState
import com.ticketbox.viewmodel.LedgerViewMode

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LedgerScreen(
    state: LedgerUiState,
    onMonthChange: (String) -> Unit,
    onCategoryChange: (String) -> Unit,
    onTagChange: (String) -> Unit,
    onQueryChange: (String) -> Unit,
    onClearFilters: () -> Unit,
    onSync: () -> Unit,
    onExportCsv: () -> Unit,
    onManualCreate: (ExpenseDraft) -> Unit,
    onViewModeChange: (LedgerViewMode) -> Unit,
    onEdit: (Expense) -> Unit,
    onEnterSelection: (Long?) -> Unit = {},
    onExitSelection: () -> Unit = {},
    onToggleSelect: (Long) -> Unit = {},
    onSelectAllVisible: () -> Unit = {},
    onApplyBatchCategory: (String) -> Unit = {},
    onApplyBatchTags: (String) -> Unit = {},
) {
    var showMonthPicker by rememberSaveable { mutableStateOf(false) }
    var showManualSheet by rememberSaveable { mutableStateOf(false) }
    var showLedgerTools by rememberSaveable { mutableStateOf(false) }
    var showBulkEdit by rememberSaveable { mutableStateOf(false) }
    val canExport = state.items.isNotEmpty() && !state.exporting

    if (showMonthPicker) {
        ModalBottomSheet(onDismissRequest = { showMonthPicker = false }) {
            MonthPickerSheet(
                months = state.months,
                selectedMonth = state.monthFilter,
                description = stringResource(R.string.ledger_month_picker_description),
                onSelectMonth = { month ->
                    onMonthChange(month)
                    showMonthPicker = false
                },
            )
        }
    }

    if (showManualSheet && !state.readOnly) {
        ModalBottomSheet(onDismissRequest = { showManualSheet = false }) {
            ManualExpenseSheet(
                categories = state.categories,
                saving = state.creatingManual,
                onCreate = { draft ->
                    showManualSheet = false
                    onManualCreate(draft)
                },
                onDismiss = { showManualSheet = false },
            )
        }
    }

    if (showLedgerTools) {
        ModalBottomSheet(onDismissRequest = { showLedgerTools = false }) {
            LedgerToolsSheet(
                state = state,
                canExport = canExport,
                onCategoryChange = onCategoryChange,
                onTagChange = onTagChange,
                onQueryChange = onQueryChange,
                onClearFilters = onClearFilters,
                onSync = onSync,
                onExportCsv = onExportCsv,
                onDismiss = { showLedgerTools = false },
            )
        }
    }

    if (showBulkEdit && state.selectionMode && !state.readOnly) {
        ModalBottomSheet(onDismissRequest = { showBulkEdit = false }) {
            LedgerBulkEditSheet(
                selectedCount = state.selectedCount,
                selectedHaveTags = state.selectedHaveTags,
                categories = state.categories,
                applying = state.applyingBatch,
                onApplyCategory = {
                    showBulkEdit = false
                    onApplyBatchCategory(it)
                },
                onApplyTags = {
                    showBulkEdit = false
                    onApplyBatchTags(it)
                },
            )
        }
    }

    val resources = LocalContext.current.resources
    val groupedItems = remember(state.items, resources) { groupLedgerExpenses(resources, state.items) }

    AppScrollableContent(
        role = AppPageRole.Ledger,
        isRefreshing = state.syncing,
        onRefresh = onSync,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            if (state.selectionMode) {
                LedgerSelectionBar(
                    selectedCount = state.selectedCount,
                    applying = state.applyingBatch,
                    onExit = onExitSelection,
                    onSelectAll = onSelectAllVisible,
                    onEdit = { showBulkEdit = true },
                )
            } else {
                LedgerFilterPanel(
                    state = state,
                    onOpenMonthPicker = { showMonthPicker = true },
                    onOpenTools = { showLedgerTools = true },
                    onManualAdd = { if (!state.readOnly) showManualSheet = true },
                    onCategoryChange = onCategoryChange,
                    onViewModeChange = onViewModeChange,
                )
            }
        }
        if (state.items.isEmpty()) {
            item {
                EmptyLedgerState(
                    state = state,
                    onClearFilters = onClearFilters,
                    onSync = onSync,
                    onManualAdd = { if (!state.readOnly) showManualSheet = true },
                )
            }
        }
        groupedItems.forEach { group ->
            item(key = "ledger-day-${group.key}") {
                LedgerDayHeader(group.label)
            }
            items(group.items, key = { it.id }) { expense ->
                val selected = expense.id in state.selectedIds
                val onToggle = { onToggleSelect(expense.id) }
                val onLongPress = { onEnterSelection(expense.id) }
                when (state.viewMode) {
                    LedgerViewMode.Card -> LedgerExpenseCard(
                        expense = expense,
                        onEdit = { onEdit(expense) },
                        selectionMode = state.selectionMode,
                        selected = selected,
                        onToggleSelect = onToggle,
                        onLongPress = onLongPress,
                    )
                    LedgerViewMode.List -> LedgerExpenseListRow(
                        expense = expense,
                        onEdit = { onEdit(expense) },
                        selectionMode = state.selectionMode,
                        selected = selected,
                        onToggleSelect = onToggle,
                        onLongPress = onLongPress,
                    )
                    LedgerViewMode.Table -> LedgerExpenseTableRow(
                        expense = expense,
                        onEdit = { onEdit(expense) },
                        selectionMode = state.selectionMode,
                        selected = selected,
                        onToggleSelect = onToggle,
                        onLongPress = onLongPress,
                    )
                }
            }
        }
    }
}

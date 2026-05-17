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
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.MonthPickerSheet
import com.ticketbox.ui.design.LocalCurrencyCode
import com.ticketbox.ui.screens.ledger.EmptyLedgerState
import com.ticketbox.ui.screens.ledger.LedgerDayHeader
import com.ticketbox.ui.screens.ledger.LedgerExpenseCard
import com.ticketbox.ui.screens.ledger.LedgerFilterPanel
import com.ticketbox.ui.screens.ledger.LedgerToolsSheet
import com.ticketbox.viewmodel.LedgerUiState

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
    onEdit: (Expense) -> Unit,
) {
    var showMonthPicker by rememberSaveable { mutableStateOf(false) }
    var showManualSheet by rememberSaveable { mutableStateOf(false) }
    var showLedgerTools by rememberSaveable { mutableStateOf(false) }
    val selectedCurrency = LocalCurrencyCode.current
    val canExport = state.items.isNotEmpty() && !state.exporting

    if (showMonthPicker) {
        ModalBottomSheet(onDismissRequest = { showMonthPicker = false }) {
            MonthPickerSheet(
                months = state.months,
                selectedMonth = state.monthFilter,
                description = "选择后会刷新账本。历史月份多了以后可以上下滑动。",
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
                initialCurrency = selectedCurrency,
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

    val groupedItems = remember(state.items) { groupLedgerExpenses(state.items) }

    AppScrollableContent(
        role = AppPageRole.Ledger,
        isRefreshing = state.syncing,
        onRefresh = onSync,
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item {
            LedgerFilterPanel(
                state = state,
                onOpenMonthPicker = { showMonthPicker = true },
                onOpenTools = { showLedgerTools = true },
                onManualAdd = { if (!state.readOnly) showManualSheet = true },
                onCategoryChange = onCategoryChange,
            )
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
                LedgerDayHeader(group.label, modifier = Modifier.animateItem())
            }
            items(group.items, key = { it.id }) { expense ->
                LedgerExpenseCard(
                    modifier = Modifier.animateItem(),
                    expense = expense,
                    onEdit = { onEdit(expense) },
                )
            }
        }
    }
}

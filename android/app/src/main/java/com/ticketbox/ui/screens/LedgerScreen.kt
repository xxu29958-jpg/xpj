package com.ticketbox.ui.screens

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.components.MonthPickerSheet
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.ledger.LedgerBulkEditSheet
import com.ticketbox.ui.screens.ledger.LedgerDayHeader
import com.ticketbox.ui.screens.ledger.LedgerEmptyOrFirstSync
import com.ticketbox.ui.screens.ledger.LedgerExpenseCard
import com.ticketbox.ui.screens.ledger.LedgerExpenseListRow
import com.ticketbox.ui.screens.ledger.LedgerExpenseTableRow
import com.ticketbox.ui.screens.ledger.LedgerFilterPanel
import com.ticketbox.ui.screens.ledger.LedgerInlineStatusMessage
import com.ticketbox.ui.screens.ledger.LedgerSelectionBar
import com.ticketbox.ui.screens.ledger.LedgerToolsSheet
import com.ticketbox.viewmodel.LedgerUiState
import com.ticketbox.viewmodel.LedgerViewMode

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class)
@Composable
fun LedgerScreen(
    state: LedgerUiState,
    // 启动器「记一笔」shortcut 的一次性信号；true 时自动打开手动记账表单，[onManualEntryConsumed]
    // 复位避免 tab 重入重复弹。默认 false/no-op = 普通进入此屏，不自动弹。
    openManualEntryRequested: Boolean = false,
    onManualEntryConsumed: () -> Unit = {},
    onMonthChange: (String) -> Unit,
    onCategoryChange: (String) -> Unit,
    onTagChange: (String) -> Unit,
    onQueryChange: (String) -> Unit,
    onClearFilters: () -> Unit,
    onSync: () -> Unit,
    onExportCsv: () -> Unit,
    // A3 IA: 从账本工具表进入「拆账中心」二级页。默认 no-op 保旧调用方/预览。
    onOpenBillSplit: () -> Unit = {},
    // 清算 / 关系账入口从洞察移到账本工具表；默认 no-op 保旧调用方/预览。
    onOpenDebts: () -> Unit = {},
    onOpenReceivables: () -> Unit = {},
    onOpenRepaymentDrafts: () -> Unit = {},
    onOpenGlobalSearch: () -> Unit = {},
    onManualCreate: (ExpenseDraft) -> Unit,
    onViewModeChange: (LedgerViewMode) -> Unit,
    onEdit: (Expense) -> Unit,
    onEnterSelection: (Long?) -> Unit = {},
    onExitSelection: () -> Unit = {},
    onToggleSelect: (Long) -> Unit = {},
    onSelectAllVisible: () -> Unit = {},
    onApplyBatchCategory: (String) -> Unit = {},
    onApplyBatchTags: (String) -> Unit = {},
    onManualCreateSettled: () -> Unit = {},
    onBatchSettled: () -> Unit = {},
) {
    var showMonthPicker by rememberSaveable { mutableStateOf(false) }
    var showManualSheet by rememberSaveable { mutableStateOf(false) }
    var showLedgerTools by rememberSaveable { mutableStateOf(false) }
    var showBulkEdit by rememberSaveable { mutableStateOf(false) }
    val canExport = state.items.isNotEmpty() && !state.exporting

    // Close the manual sheet only on CONFIRMED success; failure keeps it open
    // (with the typed form intact) showing manualCreateError inline.
    LaunchedEffect(state.manualCreateDone) {
        if (state.manualCreateDone) {
            showManualSheet = false
            onManualCreateSettled()
        }
    }

    // Close the batch-edit sheet only once applyConfirmedBatch RESOLVES (batchDone),
    // not eagerly in the onApply lambda — so `applying` disables the buttons during
    // the in-flight call and a typed tag isn't lost mid-flight. Closes on both
    // success and failure because the synced/queued/failed outcome is page-level.
    LaunchedEffect(state.batchDone) {
        if (state.batchDone) {
            showBulkEdit = false
            onBatchSettled()
        }
    }

    // 启动器「记一笔」shortcut：信号置位即拉起手动记账表单（只读角色不弹，写入也会被
    // 后端 403）。消费后复位，tab 切走再切回不重复弹。
    LaunchedEffect(openManualEntryRequested) {
        if (openManualEntryRequested) {
            onManualEntryConsumed()
            if (!state.readOnly) showManualSheet = true
        }
    }

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
        val dismissManualSheet = {
            showManualSheet = false
            onManualCreateSettled()
        }
        ModalBottomSheet(onDismissRequest = dismissManualSheet) {
            ManualExpenseSheet(
                categories = state.categories,
                saving = state.creatingManual,
                recentMerchants = state.recentMerchants,
                errorMessage = state.manualCreateError?.asString(),
                onCreate = onManualCreate,
                onDismiss = dismissManualSheet,
            )
        }
    }

    if (showLedgerTools) {
        ModalBottomSheet(onDismissRequest = { showLedgerTools = false }) {
            val openSecondaryPage: (() -> Unit) -> Unit = { open ->
                showLedgerTools = false
                open()
            }
            LedgerToolsSheet(
                state = state,
                canExport = canExport,
                onCategoryChange = onCategoryChange,
                onTagChange = onTagChange,
                onQueryChange = onQueryChange,
                onClearFilters = onClearFilters,
                onViewModeChange = onViewModeChange,
                onSync = onSync,
                onExportCsv = onExportCsv,
                // 先收起工具表(否则二级页 overlay 会被 ModalBottomSheet 盖住), 再切到对应二级页。
                onOpenBillSplit = { openSecondaryPage(onOpenBillSplit) },
                onOpenDebts = { openSecondaryPage(onOpenDebts) },
                onOpenReceivables = { openSecondaryPage(onOpenReceivables) },
                onOpenRepaymentDrafts = { openSecondaryPage(onOpenRepaymentDrafts) },
                onOpenGlobalSearch = { openSecondaryPage(onOpenGlobalSearch) },
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
                onApplyCategory = onApplyBatchCategory,
                onApplyTags = onApplyBatchTags,
            )
        }
    }

    val resources = LocalContext.current.resources
    val groupedItems = remember(state.items, resources) { groupLedgerExpenses(resources, state.items) }

    AppScrollableContent(
        role = AppPageRole.Ledger,
        isRefreshing = state.syncing,
        onRefresh = onSync,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
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
                    onMonthChange = onMonthChange,
                )
            }
        }
        val authorityTone = ledgerAuthorityTone(state)
        if (authorityTone != DataAuthorityTone.Backend) {
            item {
                AppDataAuthorityStrip(
                    tone = authorityTone,
                    localCacheBodyRes = R.string.components_data_authority_ledger_cache_body,
                )
            }
        }
        state.message?.let { message ->
            item { LedgerInlineStatusMessage(message = message) }
        }
        if (state.items.isEmpty()) {
            // 8.4: first-ever sync (no cache + nothing synced before) shows a
            // skeleton list instead of the empty-state card, so the user doesn't
            // see "还没有账单" flash before the first data lands. Any later sync
            // has a non-null lastSyncAt (returning user), so this never replaces
            // the genuine empty state. Both branches are extracted composables to
            // keep this item{} body shallow (NestedBlockDepth gate).
            item {
                LedgerEmptyOrFirstSync(
                    state = state,
                    onClearFilters = onClearFilters,
                    onSync = onSync,
                    onManualAdd = { if (!state.readOnly) showManualSheet = true },
                )
            }
        }
        groupedItems.forEach { group ->
            // stickyHeader pins the current day's header (date + subtotal) to the
            // top edge while its rows scroll under it, so the day context never
            // disappears mid-scroll.
            stickyHeader(key = "ledger-day-${group.key}") {
                LedgerDayHeader(group.label, group.dayTotalCents)
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

private fun ledgerAuthorityTone(state: LedgerUiState): DataAuthorityTone = when {
    state.readOnly -> DataAuthorityTone.ReadOnly
    state.syncing -> DataAuthorityTone.Refreshing
    state.syncedInCurrentSession -> DataAuthorityTone.Backend
    else -> DataAuthorityTone.LocalCache
}

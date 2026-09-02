package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.Composable
import com.ticketbox.R
import com.ticketbox.ui.components.AppAdaptiveSupportingPane
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.ledger.LedgerFilterPanel
import com.ticketbox.ui.screens.ledger.LedgerFilterPanelActions
import com.ticketbox.ui.screens.ledger.LedgerInlineStatusMessage
import com.ticketbox.ui.screens.ledger.LedgerSelectionBar
import com.ticketbox.ui.screens.ledger.ledgerPageMessageVisible
import com.ticketbox.viewmodel.LedgerUiState

@Composable
internal fun LedgerSupportingPane(
    state: LedgerUiState,
    actions: LedgerScreenActions,
    chromeState: LedgerScreenChromeState,
) {
    val authorityTone = ledgerAuthorityTone(state)
    AppAdaptiveSupportingPane(
        role = AppPageRole.Ledger,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        LedgerTopChrome(
            state = state,
            actions = actions,
            chromeState = chromeState,
            showSummaryHeader = false,
        )
        if (ledgerStatusVisible(state, authorityTone)) {
            LedgerStatusContent(state = state, authorityTone = authorityTone)
        }
    }
}

@Composable
internal fun LedgerTopChrome(
    state: LedgerUiState,
    actions: LedgerScreenActions,
    chromeState: LedgerScreenChromeState,
    showSummaryHeader: Boolean,
) {
    if (state.selectionMode) {
        LedgerSelectionBar(
            selectedCount = state.selectedCount,
            applying = state.applyingBatch,
            onExit = actions.onExitSelection,
            onSelectAll = actions.onSelectAllVisible,
            onEdit = { chromeState.showBulkEdit = true },
        )
    } else {
        LedgerFilterPanel(
            state = state,
            actions = LedgerFilterPanelActions(
                onOpenMonthPicker = { chromeState.showMonthPicker = true },
                onOpenTools = { chromeState.showLedgerTools = true },
                onOpenSearch = actions.onOpenGlobalSearch,
                onManualAdd = { if (!state.readOnly) chromeState.showManualSheet = true },
                onMonthChange = actions.onMonthChange,
            ),
            recordCtaSlot = ledgerRecordCtaSlot(
                readOnly = state.readOnly,
                hasItems = state.items.isNotEmpty(),
                isFirstSync = state.isFirstSync,
                hasFilters = state.filter.hasFilters,
            ),
            showSummaryHeader = showSummaryHeader,
        )
    }
}

@Composable
internal fun LedgerStatusContent(
    state: LedgerUiState,
    authorityTone: DataAuthorityTone,
) {
    Column(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        if (ledgerPermissionStripVisible(state)) {
            AppDataAuthorityStrip(tone = DataAuthorityTone.ReadOnly)
        }
        if (authorityTone != DataAuthorityTone.Backend) {
            AppDataAuthorityStrip(
                tone = authorityTone,
                localCacheBodyRes = R.string.components_data_authority_ledger_cache_body,
            )
        }
        state.message?.takeIf(::ledgerPageMessageVisible)?.let { message ->
            LedgerInlineStatusMessage(message = message, tone = state.messageTone)
        }
    }
}

internal fun ledgerStatusVisible(
    state: LedgerUiState,
    authorityTone: DataAuthorityTone,
): Boolean = authorityTone != DataAuthorityTone.Backend ||
    ledgerPageMessageVisible(state.message) ||
    ledgerPermissionStripVisible(state)

/**
 * W2-B: 权限与新鲜度正交。tone 只表达数据新鲜度，不再被 readOnly 抢占——
 * Viewer 离线也必须看见缓存/刷新状态；只读权限由独立常驻行表达。
 */
internal fun ledgerAuthorityTone(state: LedgerUiState): DataAuthorityTone = when {
    state.showPageRefresh -> DataAuthorityTone.Refreshing
    state.syncedInCurrentSession -> DataAuthorityTone.Backend
    else -> DataAuthorityTone.LocalCache
}

/** 只读权限常驻行：与 freshness strip 独立，两者可同时出现。 */
internal fun ledgerPermissionStripVisible(state: LedgerUiState): Boolean = state.readOnly

/**
 * W2-B: 「记一笔」命令的唯一槽位（承 W2-A pendingUploadEntrySlot 纪律）——
 * 任一屏幕态最多一个入口：有内容、首次同步中、有筛选的空态都在页头
 * （记录命令不依赖列表可读）；仅无筛选的 settled 空态把入口让给空态卡。
 * Viewer 没有任何写命令入口（只读投影诚实，不渲染禁用态假按钮）。
 */
internal enum class LedgerRecordCtaSlot {
    Header,
    EmptyState,
}

internal fun ledgerRecordCtaSlot(
    readOnly: Boolean,
    hasItems: Boolean,
    isFirstSync: Boolean,
    hasFilters: Boolean,
): LedgerRecordCtaSlot? = when {
    readOnly -> null
    !hasItems && !isFirstSync && !hasFilters -> LedgerRecordCtaSlot.EmptyState
    else -> LedgerRecordCtaSlot.Header
}

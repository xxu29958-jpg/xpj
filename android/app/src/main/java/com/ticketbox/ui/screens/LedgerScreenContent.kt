package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.listSaver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import com.ticketbox.R
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.ledger.LedgerDaySectionActions
import com.ticketbox.ui.screens.ledger.LedgerDaySectionState
import com.ticketbox.ui.screens.ledger.LedgerEmptyOrFirstSync
import com.ticketbox.ui.screens.ledger.LedgerFilterPanel
import com.ticketbox.ui.screens.ledger.LedgerInlineStatusMessage
import com.ticketbox.ui.screens.ledger.LedgerSelectionBar
import com.ticketbox.ui.screens.ledger.ledgerDaySection
import com.ticketbox.ui.screens.ledger.shouldCompactLedgerDayGroups
import com.ticketbox.viewmodel.LedgerUiState

private const val LEDGER_DAY_KEY_SEPARATOR = ","

@Composable
internal fun LedgerContent(
    state: LedgerUiState,
    actions: LedgerScreenActions,
    chromeState: LedgerScreenChromeState,
) {
    val resources = LocalContext.current.resources
    val groupedItems = remember(state.items, resources) { groupLedgerExpenses(resources, state.items) }
    val foldState = rememberLedgerDayFoldState(state)
    val compactDayGroups = !state.selectionMode &&
        shouldCompactLedgerDayGroups(groupedItems.size, state.items.size)

    AppScrollableContent(
        role = AppPageRole.Ledger,
        isRefreshing = state.showPageRefresh,
        onRefresh = actions.onSync,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        item { LedgerTopChrome(state = state, actions = actions, chromeState = chromeState) }
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
            item {
                LedgerEmptyOrFirstSync(
                    state = state,
                    onClearFilters = actions.onClearFilters,
                    onSync = actions.onSync,
                    onManualAdd = { if (!state.readOnly) chromeState.showManualSheet = true },
                )
            }
        }
        ledgerDaySectionsContent(
            groupedItems = groupedItems,
            state = state,
            actions = actions,
            foldState = foldState,
            compactDayGroups = compactDayGroups,
        )
    }
}

@Composable
private fun LedgerTopChrome(
    state: LedgerUiState,
    actions: LedgerScreenActions,
    chromeState: LedgerScreenChromeState,
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
            onOpenMonthPicker = { chromeState.showMonthPicker = true },
            onOpenTools = { chromeState.showLedgerTools = true },
            onManualAdd = { if (!state.readOnly) chromeState.showManualSheet = true },
            onMonthChange = actions.onMonthChange,
        )
    }
}

private fun LazyListScope.ledgerDaySectionsContent(
    groupedItems: List<LedgerExpenseGroup>,
    state: LedgerUiState,
    actions: LedgerScreenActions,
    foldState: LedgerDayFoldState,
    compactDayGroups: Boolean,
) {
    groupedItems.forEachIndexed { index, group ->
        val expanded = ledgerDayExpanded(
            groupKey = group.key,
            groupIndex = index,
            compactGroups = compactDayGroups,
            expandedKeys = foldState.expandedKeys,
            collapsedKeys = foldState.collapsedKeys,
        )
        ledgerDaySection(
            group = group,
            sectionState = LedgerDaySectionState(
                viewMode = state.viewMode,
                selectionMode = state.selectionMode,
                selectedIds = state.selectedIds,
                compactGroups = compactDayGroups,
                expanded = expanded,
            ),
            actions = LedgerDaySectionActions(
                onEdit = actions.onEdit,
                onEnterSelection = actions.onEnterSelection,
                onToggleSelect = actions.onToggleSelect,
                onToggleGroup = { foldState.toggle(group.key, expanded) },
            ),
        )
    }
}

@Composable
private fun rememberLedgerDayFoldState(state: LedgerUiState): LedgerDayFoldState {
    return rememberSaveable(
        state.monthFilter,
        state.categoryFilter,
        state.tagFilter,
        state.query,
        state.items.size,
        saver = LedgerDayFoldStateSaver,
    ) { LedgerDayFoldState() }
}

private fun ledgerAuthorityTone(state: LedgerUiState): DataAuthorityTone = when {
    state.readOnly -> DataAuthorityTone.ReadOnly
    state.syncing -> DataAuthorityTone.Refreshing
    state.syncedInCurrentSession -> DataAuthorityTone.Backend
    else -> DataAuthorityTone.LocalCache
}

private fun ledgerDayExpanded(
    groupKey: String,
    groupIndex: Int,
    compactGroups: Boolean,
    expandedKeys: List<String>,
    collapsedKeys: List<String>,
): Boolean = when {
    !compactGroups -> true
    groupKey in expandedKeys -> true
    groupKey in collapsedKeys -> false
    else -> groupIndex == 0
}

private class LedgerDayFoldState(
    expandedKeys: List<String> = emptyList(),
    collapsedKeys: List<String> = emptyList(),
) {
    var expandedKeys by mutableStateOf(expandedKeys)
    var collapsedKeys by mutableStateOf(collapsedKeys)

    fun toggle(groupKey: String, expanded: Boolean) {
        if (expanded) {
            collapsedKeys = collapsedKeys.withLedgerDayKey(groupKey)
            expandedKeys = expandedKeys.withoutLedgerDayKey(groupKey)
        } else {
            expandedKeys = expandedKeys.withLedgerDayKey(groupKey)
            collapsedKeys = collapsedKeys.withoutLedgerDayKey(groupKey)
        }
    }
}

private fun List<String>.withLedgerDayKey(key: String): List<String> {
    return if (key in this) this else this + key
}

private fun List<String>.withoutLedgerDayKey(key: String): List<String> {
    return filterNot { it == key }
}

private val LedgerDayFoldStateSaver = listSaver<LedgerDayFoldState, String>(
    save = {
        listOf(
            it.expandedKeys.joinToString(LEDGER_DAY_KEY_SEPARATOR),
            it.collapsedKeys.joinToString(LEDGER_DAY_KEY_SEPARATOR),
        )
    },
    restore = {
        LedgerDayFoldState(
            expandedKeys = it[0].toLedgerDayKeys(),
            collapsedKeys = it[1].toLedgerDayKeys(),
        )
    },
)

private fun String.toLedgerDayKeys(): List<String> {
    return split(LEDGER_DAY_KEY_SEPARATOR).filter { it.isNotBlank() }
}

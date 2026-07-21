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
import com.ticketbox.ui.components.AppAdaptivePaneScaffold
import com.ticketbox.ui.components.AppAdaptivePanePurpose
import com.ticketbox.ui.components.AppAdaptivePaneStructures
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.AppScrollableContentChrome
import com.ticketbox.ui.components.AppScrollableContentLayout
import com.ticketbox.ui.components.AppScrollableRefreshState
import com.ticketbox.ui.components.appAdaptiveSupportingPaneContent
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalAppAdaptiveLayoutPolicy
import com.ticketbox.ui.screens.ledger.LedgerDaySectionActions
import com.ticketbox.ui.screens.ledger.LedgerDaySectionState
import com.ticketbox.ui.screens.ledger.LedgerEmptyOrFirstSync
import com.ticketbox.ui.screens.ledger.LedgerHeader
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
    val adaptivePolicy = LocalAppAdaptiveLayoutPolicy.current
    val contentModel = LedgerAdaptiveContentModel(
        groupedItems = groupedItems,
        foldState = foldState,
        compactDayGroups = compactDayGroups,
        showSupportingPane = adaptivePolicy.showsSupportingPane,
    )

    AppAdaptivePaneScaffold(
        structure = AppAdaptivePaneStructures.Transactions,
        policy = adaptivePolicy,
        primaryPane = {
            LedgerPrimaryPane(
                state = state,
                actions = actions,
                chromeState = chromeState,
                contentModel = contentModel,
            )
        },
        supportingPane = appAdaptiveSupportingPaneContent(
            purpose = AppAdaptivePanePurpose.RegisterControls,
        ) {
            LedgerSupportingPane(
                state = state,
                actions = actions,
                chromeState = chromeState,
            )
        },
    )
}

private data class LedgerAdaptiveContentModel(
    val groupedItems: List<LedgerExpenseGroup>,
    val foldState: LedgerDayFoldState,
    val compactDayGroups: Boolean,
    val showSupportingPane: Boolean,
)

@Composable
private fun LedgerPrimaryPane(
    state: LedgerUiState,
    actions: LedgerScreenActions,
    chromeState: LedgerScreenChromeState,
    contentModel: LedgerAdaptiveContentModel,
) {
    AppScrollableContent(
        chrome = AppScrollableContentChrome(
            role = AppPageRole.Ledger,
            layout = AppScrollableContentLayout(
                horizontalPadding = AppSpacing.cardPaddingSmall,
                verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            ),
        ),
        refresh = AppScrollableRefreshState(
            isRefreshing = state.showPageRefresh,
            onRefresh = actions.onSync,
        ),
    ) {
        item {
            if (contentModel.showSupportingPane) {
                LedgerHeader(state = state)
            } else {
                LedgerTopChrome(
                    state = state,
                    actions = actions,
                    chromeState = chromeState,
                    showSummaryHeader = true,
                )
            }
        }
        val authorityTone = ledgerAuthorityTone(state)
        if (!contentModel.showSupportingPane && ledgerStatusVisible(state, authorityTone)) {
            item {
                LedgerStatusContent(state = state, authorityTone = authorityTone)
            }
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
            groupedItems = contentModel.groupedItems,
            state = state,
            actions = actions,
            foldState = contentModel.foldState,
            compactDayGroups = contentModel.compactDayGroups,
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

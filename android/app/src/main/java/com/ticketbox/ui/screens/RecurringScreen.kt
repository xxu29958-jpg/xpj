package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.repository.RecurringItemDraft
import com.ticketbox.data.repository.RecurringItemPatch
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.components.AppSegmentedControl
import com.ticketbox.ui.components.AppSegmentedItem
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppButtonIcons
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.screens.recurring.RecurringCandidatesCard
import com.ticketbox.ui.screens.recurring.RecurringConflictAction
import com.ticketbox.ui.screens.recurring.RecurringConflictBanner
import com.ticketbox.ui.screens.recurring.RecurringConflictModel
import com.ticketbox.ui.screens.recurring.RecurringDerivedModel
import com.ticketbox.ui.screens.recurring.RecurringEditorEnvironment
import com.ticketbox.ui.screens.recurring.RecurringEditorSheetHost
import com.ticketbox.ui.screens.recurring.RecurringHeroSection
import com.ticketbox.ui.screens.recurring.RecurringItemsCard
import com.ticketbox.ui.screens.recurring.RecurringItemsCardState
import com.ticketbox.ui.screens.recurring.RecurringPendingSection
import com.ticketbox.ui.screens.recurring.RecurringReadSource
import com.ticketbox.ui.screens.recurring.RecurringTab
import com.ticketbox.ui.screens.recurring.RecurringTabCounts
import com.ticketbox.ui.screens.recurring.recurringDefaultTab
import com.ticketbox.ui.screens.recurring.recurringHasReadableData
import com.ticketbox.ui.screens.recurring.recurringScreenDerived
import com.ticketbox.ui.screens.recurring.rememberRecurringEditorHostState
import com.ticketbox.ui.screens.recurring.resolveRecurringDuplicateConflict
import com.ticketbox.viewmodel.RecurringListLoadState
import com.ticketbox.viewmodel.RecurringUiState

/**
 * 正式计划与观察建议分区阅读；原待同步在两个分区均可见，不计入计划总额。
 * 状态筛选与原编辑任务独立保留，viewer 继续浏览但没有写入口。
 */
@Composable
fun RecurringScreen(
    state: RecurringUiState,
    actions: RecurringScreenActions,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    var selectedTab by rememberSaveable { mutableStateOf(recurringDefaultTab) }
    var showCandidates by rememberSaveable { mutableStateOf(false) }
    val editorHost = rememberRecurringEditorHostState(
        editorEpoch = state.editorEpoch,
        runtimeId = state.editorRuntimeId,
    )
    val derived = recurringScreenDerived(state, selectedTab)
    val hasReadableData = recurringHasReadableData(state)
    val callbacks = RecurringScreenCallbacks(
        onCreate = { editorHost.openCreate(currencyDisplay.homeCurrency) },
        onEdit = { item -> editorHost.openEdit(item, currencyDisplay.homeCurrency) },
        onSelectTab = { selectedTab = it },
        onConflictAction = { model ->
            when (model.action) {
                RecurringConflictAction.EditExisting ->
                    state.items.firstOrNull { it.publicId == model.publicId }
                        ?.let { editorHost.openEdit(it, currencyDisplay.homeCurrency) }
                RecurringConflictAction.RestoreArchived -> {
                    editorHost.dismiss()
                    model.rowVersion?.let { actions.items.onRestore(model.publicId, it) }
                }
                RecurringConflictAction.Unavailable -> Unit
            }
        },
    )

    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Stats,
            title = stringResource(R.string.recurring_header_title),
            subtitle = stringResource(R.string.recurring_header_subtitle),
            backText = stringResource(R.string.recurring_back_to_stats),
            onBack = actions.onBack,
            hasBottomBar = actions.onBack == null,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
        ),
        refresh = AppSecondaryRefreshState(
            isRefreshing = ReadableRefreshIndicator.isActive(
                loading = state.loading,
                hasReadableData = hasReadableData,
            ),
            onRefresh = actions.onRefresh,
        ),
        slots = AppSecondaryPageSlots(
            actions = {
                if (!state.canModify) {
                    StatusPill(
                        text = stringResource(R.string.recurring_badge_readonly),
                        tone = LocalStateTokens.current.warn,
                    )
                }
                AppSegmentedControl(
                    options = listOf(
                        AppSegmentedItem(false, stringResource(R.string.recurring_section_formal)),
                        AppSegmentedItem(true, stringResource(R.string.recurring_section_suggestions)),
                    ),
                    selectedValue = showCandidates,
                    onValueChange = { showCandidates = it },
                )
            },
            bottomBar = if (state.canModify && !showCandidates && editorHost.editor == null) {
                {
                    AppFloatingActionBar {
                        AppPrimaryButton(
                            modifier = Modifier.fillMaxWidth(),
                            text = stringResource(R.string.recurring_add_cta),
                            icons = AppButtonIcons(leading = Icons.Filled.Add),
                            enabled = !state.manualSaveInFlight,
                            onClick = callbacks.onCreate,
                        )
                    }
                }
            } else null,
        ),
    ) {
        recurringOverviewSection(state, derived, callbacks, showCandidates)
        if (showCandidates) {
            item {
                RecurringCandidatesCard(
                    section = derived.candidateSection,
                    canModify = derived.canModify,
                    onRetry = actions.onRefresh,
                    actions = actions.candidates,
                )
            }
        } else {
            item { RecurringHeroSection(model = derived.hero) }
            recurringRegistrySection(
                derived,
                actions.copy(items = actions.items.copy(onOpenHistory = actions.items.onOpenHistory.takeIf { editorHost.editor == null })),
                callbacks,
                editEnabled = !state.manualSaveInFlight,
            )
        }
    }

    RecurringEditorSheetHost(
        editor = editorHost.editor,
        uiState = state,
        environment = RecurringEditorEnvironment(
            conflict = resolveRecurringDuplicateConflict(
                state.duplicateConflict,
                state.items,
                ownerLoaded = state.itemsLoadState == RecurringListLoadState.Loaded,
            ),
            onRefresh = actions.onRefresh,
            onDismiss = editorHost::dismiss,
            onConflictAction = callbacks.onConflictAction,
        ),
        actions = actions.items,
    )
}

data class RecurringScreenActions(
    val onRefresh: () -> Unit,
    val items: RecurringItemActions,
    val candidates: RecurringCandidateActions,
    val onBack: (() -> Unit)? = null,
)

data class RecurringItemActions(
    val onPause: (String, Long) -> Unit,
    val onResume: (String, Long) -> Unit,
    val onArchive: (String) -> Unit,
    val onRestore: (String, Long) -> Unit,
    val onCreate: (RecurringItemDraft) -> Long,
    val onEdit: (RecurringItem, RecurringItemPatch) -> Long,
    val onOpenOccurrence: (RecurringItem) -> Unit = {},
    val onOpenHistory: ((RecurringItem) -> Unit)? = null,
)

data class RecurringCandidateActions(
    val onConfirmCandidate: (RecurringCandidate) -> Unit,
)

internal data class RecurringScreenCallbacks(
    val onCreate: () -> Unit,
    val onEdit: (RecurringItem) -> Unit,
    val onSelectTab: (RecurringTab) -> Unit,
    val onConflictAction: (RecurringConflictModel) -> Unit,
)

private fun LazyListScope.recurringOverviewSection(
    state: RecurringUiState,
    derived: RecurringDerivedModel,
    callbacks: RecurringScreenCallbacks,
    showCandidates: Boolean,
) {
    if (!showCandidates) {
        item { RecurringReadSource(state.itemsFetchedAt, state.itemsFromCache, state.loading) }
    }
    val visibleBody = if (showCandidates) derived.candidateSection.bodyState else derived.itemSection.bodyState
    state.message?.takeIf {
        state.duplicateConflict == null && visibleBody != ReadableListBodyState.LoadFailed
    }?.let { message ->
        item { AppStatusBanner(message = message, tone = state.messageTone) }
    }
    resolveRecurringDuplicateConflict(
        state.duplicateConflict,
        state.items,
        ownerLoaded = state.itemsLoadState == RecurringListLoadState.Loaded,
    )?.let { conflict ->
        if (state.canModify) {
            item { RecurringConflictBanner(model = conflict, onAction = callbacks.onConflictAction) }
        }
    }
    if (state.pendingIntents.isNotEmpty()) {
        item {
            RecurringPendingSection(
                intents = state.pendingIntents,
                items = state.items,
            )
        }
    }
}

private fun LazyListScope.recurringRegistrySection(
    derived: RecurringDerivedModel,
    actions: RecurringScreenActions,
    callbacks: RecurringScreenCallbacks,
    editEnabled: Boolean,
) {
    item {
        RecurringTabRow(
            selected = derived.selectedTab,
            counts = derived.counts,
            onSelect = callbacks.onSelectTab,
        )
    }
    item {
        RecurringItemsCard(
            state = RecurringItemsCardState(
                title = stringResource(derived.selectedTab.labelRes),
                section = derived.itemSection,
                canModify = derived.canModify,
                editEnabled = editEnabled,
            ),
            onRetry = actions.onRefresh,
            onEdit = callbacks.onEdit,
            actions = actions.items,
        )
    }
}

@Composable
private fun RecurringTabRow(
    selected: RecurringTab,
    counts: RecurringTabCounts,
    onSelect: (RecurringTab) -> Unit,
) {
    AppSegmentedControl(
        options = RecurringTab.entries.map { tab ->
            val count = when (tab) {
                RecurringTab.Upcoming -> counts.upcoming
                RecurringTab.Active -> counts.active
                RecurringTab.Paused -> counts.paused
                RecurringTab.Archived -> counts.archived
            }
            AppSegmentedItem(
                value = tab,
                label = if (counts.factual) {
                    stringResource(R.string.recurring_tab_label_count, stringResource(tab.labelRes), count)
                } else {
                    stringResource(tab.labelRes)
                },
            )
        },
        selectedValue = selected,
        onValueChange = onSelect,
    )
}

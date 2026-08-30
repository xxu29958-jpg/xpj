package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
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
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppPageRole
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
import com.ticketbox.ui.screens.recurring.RecurringCandidateSectionOptions
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
 * 固定支出主页。信息层级（A3 合同）：计划总额 hero → 主 CTA「添加固定支出」→
 * 待同步（不进总额，WAITING/CONFLICT/FAILED 三态诚实呈现）→ registry 列表
 * （名称/计划金额/下次日期/状态）→ 候选建议（辅助，降权）。viewer 不见表单、
 * 不见失效 CTA，只在页头看到只读标记。撞单给可行动出口，不只红色错误。
 */
@Composable
fun RecurringScreen(
    state: RecurringUiState,
    actions: RecurringScreenActions,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    var selectedTab by rememberSaveable { mutableStateOf(recurringDefaultTab) }
    val editorHost = rememberRecurringEditorHostState(
        editorEpoch = state.editorEpoch,
        runtimeId = state.editorRuntimeId,
    )
    val derived = recurringScreenDerived(state, selectedTab)
    val hasReadableData = recurringHasReadableData(state)
    val commandsEnabled = recurringCommandsEnabled(
        manualSaveInFlight = state.manualSaveInFlight,
        mutationInFlight = state.mutationInFlight,
    )
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
            isRefreshing = recurringScreenActivityActive(
                loading = state.loading,
                hasReadableData = hasReadableData,
                mutationInFlight = state.mutationInFlight,
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
            },
        ),
    ) {
        recurringOverviewSection(state, derived, currencyDisplay, callbacks, commandsEnabled)
        recurringRegistrySection(
            derived,
            currencyDisplay,
            actions,
            callbacks,
            commandsEnabled = commandsEnabled,
        )
    }

    RecurringEditorSheetHost(
        editor = editorHost.editor,
        uiState = state,
        environment = RecurringEditorEnvironment(
            currencyDisplay = currencyDisplay,
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
    currencyDisplay: CurrencyDisplay,
    callbacks: RecurringScreenCallbacks,
    commandsEnabled: Boolean,
) {
    state.message?.takeIf {
        recurringStatusMessageVisible(
            hasDuplicateConflict = state.duplicateConflict != null,
            itemsBodyState = derived.itemSection.bodyState,
        )
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
    item {
        RecurringHeroSection(model = derived.hero, currencyDisplay = currencyDisplay)
    }
    if (state.canModify) {
        item {
            AppPrimaryButton(
                modifier = Modifier.fillMaxWidth(),
                text = stringResource(R.string.recurring_add_cta),
                icon = Icons.Filled.Add,
                enabled = commandsEnabled,
                onClick = callbacks.onCreate,
            )
        }
    }
    if (state.pendingIntents.isNotEmpty()) {
        item {
            RecurringPendingSection(
                intents = state.pendingIntents,
                items = state.items,
                currencyDisplay = currencyDisplay,
            )
        }
    }
}

private fun LazyListScope.recurringRegistrySection(
    derived: RecurringDerivedModel,
    currencyDisplay: CurrencyDisplay,
    actions: RecurringScreenActions,
    callbacks: RecurringScreenCallbacks,
    commandsEnabled: Boolean,
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
                currencyDisplay = currencyDisplay,
                canModify = derived.canModify,
                commandsEnabled = commandsEnabled,
            ),
            onRetry = actions.onRefresh,
            onEdit = callbacks.onEdit,
            actions = actions.items,
        )
    }
    item {
        RecurringCandidatesCard(
            section = derived.candidateSection,
            currencyDisplay = currencyDisplay,
            options = RecurringCandidateSectionOptions(
                canModify = derived.canModify,
                itemsHealthy = derived.itemSection.bodyState != ReadableListBodyState.LoadFailed,
                confirmEnabled = commandsEnabled,
            ),
            onRetry = actions.onRefresh,
            actions = actions.candidates,
        )
    }
}

@Composable
private fun RecurringTabRow(
    selected: RecurringTab,
    counts: RecurringTabCounts,
    onSelect: (RecurringTab) -> Unit,
) {
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        RecurringTab.entries.forEach { tab ->
            val count = when (tab) {
                RecurringTab.Upcoming -> counts.upcoming
                RecurringTab.Active -> counts.active
                RecurringTab.Paused -> counts.paused
                RecurringTab.Archived -> counts.archived
            }
            AppFilterChip(
                selected = selected == tab,
                onClick = { onSelect(tab) },
                label = if (counts.factual) {
                    stringResource(R.string.recurring_tab_label_count, stringResource(tab.labelRes), count)
                } else {
                    stringResource(tab.labelRes)
                },
            )
        }
    }
}

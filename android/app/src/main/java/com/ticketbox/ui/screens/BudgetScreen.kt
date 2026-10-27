package com.ticketbox.ui.screens

import com.ticketbox.ui.components.FinancialMonthInput

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.Alignment
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.repository.PendingBudgetSave
import com.ticketbox.ui.screens.budget.BudgetPendingSaves
import com.ticketbox.ui.screens.budget.BudgetReadSource
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppBusyGuardedSheet
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSecondaryPageHeader
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.AppScrollableContentChrome
import com.ticketbox.ui.components.AppScrollableContentLayout
import com.ticketbox.ui.components.AppScrollableRefreshState
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.components.displayMonthLabel
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppAdaptiveContentWidth
import com.ticketbox.ui.screens.budget.BudgetCachedHeader
import com.ticketbox.ui.screens.budget.BudgetEditorActions
import com.ticketbox.ui.screens.budget.BudgetEditorSection
import com.ticketbox.ui.screens.budget.BudgetPageDecision
import com.ticketbox.ui.screens.budget.BudgetPageStatus
import com.ticketbox.ui.screens.budget.BudgetSummarySection
import com.ticketbox.ui.screens.budget.CategoryBudgetSection
import com.ticketbox.ui.screens.budget.ExcludedBreakdownSection
import com.ticketbox.ui.screens.budget.MonthSwitcher
import com.ticketbox.ui.screens.budget.budgetInlineLoadError
import com.ticketbox.ui.screens.budget.budgetPageDecision
import com.ticketbox.viewmodel.BudgetUiState

data class BudgetScreenActions(
    val onRefresh: () -> Unit,
    val onPreviousMonth: () -> Unit,
    val onNextMonth: () -> Unit,
    val onTotalAmountChange: (String) -> Unit,
    val onRolloverAmountChange: (String) -> Unit,
    val onNonMonthlyAmountChange: (String) -> Unit,
    val onExcludedCategoriesChange: (String) -> Unit,
    val onCategoryRowChange: (Int, String, String) -> Unit,
    val onAddCategoryRow: () -> Unit,
    val onRemoveCategoryRow: (Int) -> Unit,
    val onSave: () -> Unit,
    val onRecoverSave: (PendingBudgetSave, Boolean) -> Unit,
    val onArchive: (Long) -> Unit,
    val onSelectMonth: (String) -> Unit,
)

@Composable
fun BudgetScreen(
    state: BudgetUiState,
    actions: BudgetScreenActions,
    onHistory: () -> Unit,
    onBack: (() -> Unit)? = null,
    backText: String? = null,
) {
    BudgetScreenContent(state = state, actions = actions, onBack = onBack, onHistory = onHistory, backText = backText)
}

@Composable
private fun BudgetScreenContent(
    state: BudgetUiState,
    actions: BudgetScreenActions,
    onBack: (() -> Unit)?,
    onHistory: () -> Unit,
    backText: String?,
) {
    val decision = budgetPageDecision(state)
    var editorOpen by rememberSaveable(state.binding, state.month) { mutableStateOf(false) }
    LaunchedEffect(state.binding, state.month, state.formDirty, state.hasPendingSave, state.budget?.configured, state.canModify, state.messageTone) {
        if (state.hasConfirmedSave()) {
            editorOpen = false
        } else if (state.formDirty || state.hasPendingSave || (state.canModify && state.budget?.configured == false)) editorOpen = true
    }
    BackHandler(enabled = onBack != null) { onBack?.invoke() }
    AppScrollableContent(
        chrome = AppScrollableContentChrome(
            role = AppPageRole.Stats,
            layout = AppScrollableContentLayout(hasBottomBar = onBack == null,
                contentWidth = AppAdaptiveContentWidth.Secondary,
                verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap)),
            bottomBar = if (state.canModify && state.month.isNotBlank()) ({
                AppFloatingActionBar {
                    BudgetEditEntry(firstUse = decision.status == BudgetPageStatus.NotEnabled) { editorOpen = true }
                }
            }) else null,
        ),
        refresh = AppScrollableRefreshState(
            isRefreshing = ReadableRefreshIndicator.isActive(
                loading = state.loading,
                hasReadableData = state.budget != null,
            ),
            onRefresh = actions.onRefresh,
        ),
    ) {
        item {
            if (state.fromCache) BudgetCachedHeader(backText ?: stringResource(R.string.budget_back_to_stats), onBack, onHistory)
            else AppSecondaryPageHeader(title = stringResource(R.string.budget_header_title),
                subtitle = stringResource(R.string.budget_header_subtitle, displayMonthLabel(state.month)),
                backText = backText ?: stringResource(R.string.budget_back_to_stats), onBack = onBack,
                slots = AppSecondaryPageSlots(actions = { BudgetPageActions(decision, onHistory, state.month.isNotBlank()) }))
        }
        budgetPageContent(state, actions, decision, editorOpen)
    }
    if (editorOpen) BudgetEditorSheet(state, actions) { editorOpen = false }
}

private fun BudgetUiState.hasConfirmedSave(): Boolean =
    !formDirty && !hasPendingSave && budget?.configured == true && messageTone == MessageTone.Success

@Composable
private fun BudgetEditorSheet(state: BudgetUiState, actions: BudgetScreenActions, onDismiss: () -> Unit) {
    AppBusyGuardedSheet(isSubmitting = state.saving, onDismiss = onDismiss, skipPartiallyExpanded = true) {
        AppSheetScaffold(
            title = stringResource(R.string.budget_editor_title),
            subtitle = stringResource(R.string.budget_header_subtitle, displayMonthLabel(state.month)),
            actions = {
                state.message?.let { AppStatusBanner(message = it, tone = state.messageTone) }
                AppSheetActionRow(primary = AppSheetAction(
                    stringResource(if (state.saving) R.string.common_saving else R.string.budget_editor_save), actions.onSave,
                    enabled = state.canModify && !state.saving && !state.hasPendingSave && state.formCurrency != null,
                ))
                TextButton(onClick = onDismiss, enabled = !state.saving, modifier = Modifier.fillMaxWidth()) {
                    Text(stringResource(R.string.budget_editor_back))
                }
            },
        ) {
            budgetInlineLoadError(state)?.let { AppStatusBanner(message = it, tone = MessageTone.Info) }
            if (state.saves.isNotEmpty()) BudgetPendingSaves(state.saves, state.canModify, actions.onRecoverSave)
            BudgetEditorSection(state, actions.toBudgetEditorActions())
        }
    }
}

private fun LazyListScope.budgetPageContent(state: BudgetUiState, actions: BudgetScreenActions,
    decision: BudgetPageDecision, editorOpen: Boolean) {
    val currencyDisplay = CurrencyDisplay.forRecord(state.budget?.homeCurrencyCode ?: "UNKNOWN")
    if (state.month.isBlank()) item { FinancialMonthInput(actions.onSelectMonth) }
    else if (!state.fromCache) item { MonthSwitcher(displayMonthLabel(state.month), actions.onPreviousMonth, actions.onNextMonth) }
    state.message?.takeIf { !editorOpen }?.let { message ->
        item { AppStatusBanner(message = message, tone = state.messageTone) }
    }
    budgetInlineLoadError(state)?.let { error ->
        item { AppStatusBanner(message = error, tone = MessageTone.Info) }
    }
    item { BudgetReadSource(state.fetchedAt, state.fromCache, state.loading, prominent = true) }
    item {
        BudgetSummarySection(
            state = state,
            currencyDisplay = currencyDisplay,
            onRetry = actions.onRefresh,
        )
    }
    if (!editorOpen && state.saves.isNotEmpty()) {
        item { BudgetPendingSaves(state.saves, state.canModify, actions.onRecoverSave) }
    }
    if (state.fromCache) item { MonthSwitcher(displayMonthLabel(state.month), actions.onPreviousMonth, actions.onNextMonth) }
    budgetExecutionSections(decision, currencyDisplay)
    item { com.ticketbox.ui.screens.budget.BudgetArchiveAction(state, actions.onArchive) }
}

@Composable
private fun BudgetEditEntry(firstUse: Boolean, onEdit: () -> Unit) {
    AppPrimaryButton(
        text = stringResource(if (firstUse) R.string.budget_editor_open_first else R.string.budget_editor_open),
        modifier = Modifier.fillMaxWidth().testTag("budget_edit_open"),
        onClick = onEdit,
    )
}

@Composable
private fun BudgetPageActions(decision: BudgetPageDecision, onHistory: () -> Unit, monthReady: Boolean) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        BudgetStatusBadge(decision)
        TextButton(onClick = onHistory, enabled = monthReady) { Text(stringResource(R.string.budget_history_title)) }
    }
}

@Composable
private fun BudgetStatusBadge(decision: BudgetPageDecision) {
    val stateTokens = LocalStateTokens.current
    val (text, tone) = when (decision.status) {
        BudgetPageStatus.Loading -> stringResource(R.string.budget_status_badge_loading) to stateTokens.neutral
        BudgetPageStatus.LoadFailed -> stringResource(R.string.budget_status_badge_error) to stateTokens.warn
        BudgetPageStatus.NotEnabled -> stringResource(R.string.budget_status_badge_not_enabled) to stateTokens.neutral
        BudgetPageStatus.Active -> {
            val budget = decision.configuredBudget
            if (budget?.isOverBudget == true) {
                stringResource(R.string.budget_status_badge_over) to stateTokens.warn
            } else {
                stringResource(R.string.budget_status_badge_active) to stateTokens.info
            }
        }
    }
    StatusPill(text = text, tone = tone)
}

private fun BudgetScreenActions.toBudgetEditorActions() = BudgetEditorActions(
    onTotalAmountChange = onTotalAmountChange,
    onRolloverAmountChange = onRolloverAmountChange,
    onNonMonthlyAmountChange = onNonMonthlyAmountChange,
    onExcludedCategoriesChange = onExcludedCategoriesChange,
    onCategoryRowChange = onCategoryRowChange,
    onAddCategoryRow = onAddCategoryRow,
    onRemoveCategoryRow = onRemoveCategoryRow,
)

private fun LazyListScope.budgetExecutionSections(
    decision: BudgetPageDecision,
    currencyDisplay: CurrencyDisplay,
) {
    decision.configuredBudget?.let { budget ->
        item {
            CategoryBudgetSection(
                items = budget.categoryBudgets,
                currencyDisplay = currencyDisplay,
            )
        }
        item {
            ExcludedBreakdownSection(
                items = budget.excludedBreakdown,
                currencyDisplay = currencyDisplay,
            )
        }
    }
}

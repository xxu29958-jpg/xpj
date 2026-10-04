package com.ticketbox.ui.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
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
import com.ticketbox.ui.components.AppSecondaryPageHeader
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.AppScrollableContentChrome
import com.ticketbox.ui.components.AppScrollableContentLayout
import com.ticketbox.ui.components.AppScrollableRefreshState
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.StatusPill
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
    LaunchedEffect(state.binding, state.month, state.formDirty, state.hasPendingSave, state.budget?.configured, state.canModify) {
        if (state.formDirty || state.hasPendingSave || (state.canModify && state.budget?.configured == false)) editorOpen = true
    }
    val back: (() -> Unit)? = if (editorOpen) ({ editorOpen = false }) else onBack

    BackHandler(enabled = back != null) { back?.invoke() }
    AppScrollableContent(
        chrome = AppScrollableContentChrome(
            role = AppPageRole.Stats,
            layout = AppScrollableContentLayout(hasBottomBar = onBack == null,
                contentWidth = AppAdaptiveContentWidth.Secondary,
                verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap)),
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
            if (state.fromCache && !editorOpen) BudgetCachedHeader(backText ?: stringResource(R.string.budget_back_to_stats), onBack, onHistory)
            else AppSecondaryPageHeader(title = stringResource(if (editorOpen) R.string.budget_editor_title else R.string.budget_header_title),
                subtitle = stringResource(R.string.budget_header_subtitle, state.month),
                backText = if (editorOpen) stringResource(R.string.budget_editor_back) else backText ?: stringResource(R.string.budget_back_to_stats), onBack = back,
                actions = { BudgetPageActions(decision, onHistory) })
        }
        budgetPageContent(state, actions, decision, editorOpen) { editorOpen = true }
    }
}

private fun LazyListScope.budgetPageContent(state: BudgetUiState, actions: BudgetScreenActions,
    decision: BudgetPageDecision, editorOpen: Boolean, onEdit: () -> Unit) {
    val currencyDisplay = CurrencyDisplay.forRecord(state.budget?.homeCurrencyCode ?: "UNKNOWN")
    if (!state.fromCache) item { MonthSwitcher(state.month, actions.onPreviousMonth, actions.onNextMonth) }
    state.message?.let { message ->
        item { AppStatusBanner(message = message, tone = state.messageTone) }
    }
    budgetInlineLoadError(state)?.let { error ->
        item { AppStatusBanner(message = error, tone = MessageTone.Info) }
    }
    item { BudgetReadSource(state.fetchedAt, state.fromCache, state.loading, prominent = true) }
    if (!editorOpen) item {
        BudgetSummarySection(
            state = state,
            currencyDisplay = currencyDisplay,
            onRetry = actions.onRefresh,
        )
    }
    if (state.saves.isNotEmpty()) {
        item { BudgetPendingSaves(state.saves, state.canModify, actions.onRecoverSave) }
    }
    if (state.fromCache) item { MonthSwitcher(state.month, actions.onPreviousMonth, actions.onNextMonth) }
    if (editorOpen) item {
        BudgetEditorSection(
            state = state,
            actions = actions.toBudgetEditorActions(),
        )
    }
    if (!editorOpen) {
        budgetExecutionSections(decision, currencyDisplay)
        if (state.canModify) item {
            TextButton(onClick = onEdit, modifier = Modifier.testTag("budget_edit_open")) {
                Text(stringResource(R.string.budget_editor_open))
            }
        }
        item { com.ticketbox.ui.screens.budget.BudgetArchiveAction(state, actions.onArchive) }
    }
}

@Composable
private fun BudgetPageActions(decision: BudgetPageDecision, onHistory: () -> Unit) {
    Row(verticalAlignment = Alignment.CenterVertically) {
        BudgetStatusBadge(decision)
        TextButton(onClick = onHistory) { Text(stringResource(R.string.budget_history_title)) }
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
    onSave = onSave,
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

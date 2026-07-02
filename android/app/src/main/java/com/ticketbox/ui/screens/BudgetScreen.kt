package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.SafeBadge
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.screens.budget.BudgetEditorActions
import com.ticketbox.ui.screens.budget.BudgetEditorSection
import com.ticketbox.ui.screens.budget.BudgetPageDecision
import com.ticketbox.ui.screens.budget.BudgetSummarySection
import com.ticketbox.ui.screens.budget.CategoryBudgetSection
import com.ticketbox.ui.screens.budget.ExcludedBreakdownSection
import com.ticketbox.ui.screens.budget.MonthSwitcher
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
)

@Composable
fun BudgetScreen(
    state: BudgetUiState,
    actions: BudgetScreenActions,
    onBack: (() -> Unit)? = null,
) {
    BudgetScreenContent(state = state, actions = actions, onBack = onBack)
}

@Composable
private fun BudgetScreenContent(
    state: BudgetUiState,
    actions: BudgetScreenActions,
    onBack: (() -> Unit)?,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val decision = budgetPageDecision(state)

    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(
            role = AppPageRole.Stats,
            title = stringResource(R.string.budget_header_title),
            subtitle = stringResource(R.string.budget_header_subtitle, state.month),
            backText = stringResource(R.string.budget_back_to_stats),
            onBack = onBack,
            hasBottomBar = onBack == null,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.sectionGap),
        ),
        refresh = AppSecondaryRefreshState(
            isRefreshing = ReadableRefreshIndicator.isActive(
                loading = state.loading,
                hasReadableData = state.budget != null,
            ),
            onRefresh = actions.onRefresh,
        ),
        slots = AppSecondaryPageSlots(
            actions = { SafeBadge() },
        ),
    ) {
        item {
            MonthSwitcher(
                month = state.month,
                onPreviousMonth = actions.onPreviousMonth,
                onNextMonth = actions.onNextMonth,
            )
        }
        state.message?.let { message ->
            item { Text(message.asString(), color = MaterialTheme.colorScheme.secondary) }
        }
        item {
            BudgetSummarySection(
                budget = state.budget,
                loading = state.loading && state.budget == null,
                loadError = state.loadError,
                currencyDisplay = currencyDisplay,
                onRetry = actions.onRefresh,
            )
        }
        item {
            BudgetEditorSection(
                state = state,
                actions = actions.toBudgetEditorActions(),
            )
        }
        budgetExecutionSections(decision, currencyDisplay)
    }
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

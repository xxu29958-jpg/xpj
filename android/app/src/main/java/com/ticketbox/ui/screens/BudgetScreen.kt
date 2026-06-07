package com.ticketbox.ui.screens

import androidx.activity.compose.BackHandler
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.screens.budget.BudgetEditorActions
import com.ticketbox.ui.screens.budget.BudgetEditorCard
import com.ticketbox.ui.screens.budget.BudgetHeader
import com.ticketbox.ui.screens.budget.BudgetSummaryCard
import com.ticketbox.ui.screens.budget.CategoryBudgetCard
import com.ticketbox.ui.screens.budget.ExcludedBreakdownCard
import com.ticketbox.viewmodel.BudgetUiState

@Composable
fun BudgetScreen(
    state: BudgetUiState,
    onRefresh: () -> Unit,
    onPreviousMonth: () -> Unit,
    onNextMonth: () -> Unit,
    onTotalAmountChange: (String) -> Unit,
    onRolloverAmountChange: (String) -> Unit,
    onNonMonthlyAmountChange: (String) -> Unit,
    onExcludedCategoriesChange: (String) -> Unit,
    onCategoryRowChange: (Int, String, String) -> Unit,
    onAddCategoryRow: () -> Unit,
    onRemoveCategoryRow: (Int) -> Unit,
    onSave: () -> Unit,
    onBack: (() -> Unit)? = null,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val editorActions = BudgetEditorActions(
        onTotalAmountChange = onTotalAmountChange,
        onRolloverAmountChange = onRolloverAmountChange,
        onNonMonthlyAmountChange = onNonMonthlyAmountChange,
        onExcludedCategoriesChange = onExcludedCategoriesChange,
        onCategoryRowChange = onCategoryRowChange,
        onAddCategoryRow = onAddCategoryRow,
        onRemoveCategoryRow = onRemoveCategoryRow,
        onSave = onSave,
    )

    BackHandler(enabled = onBack != null) {
        onBack?.invoke()
    }

    AppScrollableContent(
        role = AppPageRole.Stats,
        isRefreshing = state.loading,
        onRefresh = onRefresh,
        hasBottomBar = onBack == null,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
    ) {
        item {
            BudgetHeader(
                month = state.month,
                hasBottomBar = onBack == null,
                onPreviousMonth = onPreviousMonth,
                onNextMonth = onNextMonth,
                onBack = onBack,
            )
        }
        state.message?.let { message ->
            item { Text(message.asString(), color = MaterialTheme.colorScheme.secondary) }
        }
        item {
            BudgetSummaryCard(
                budget = state.budget,
                loading = state.loading,
                currencyDisplay = currencyDisplay,
            )
        }
        item {
            BudgetEditorCard(
                state = state,
                actions = editorActions,
            )
        }
        state.budget?.let { budget ->
            item {
                CategoryBudgetCard(
                    items = budget.categoryBudgets,
                    currencyDisplay = currencyDisplay,
                )
            }
            item {
                ExcludedBreakdownCard(
                    items = budget.excludedBreakdown,
                    currencyDisplay = currencyDisplay,
                )
            }
        }
    }
}

package com.ticketbox.ui.screens.budget

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppAmountInputState
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.viewmodel.BudgetUiState
import com.ticketbox.viewmodel.BudgetFormState

internal data class BudgetEditorActions(
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
internal fun BudgetEditorSection(
    state: BudgetUiState,
    actions: BudgetEditorActions,
) {
    var showOptional by rememberSaveable(state.binding, state.month) { mutableStateOf(false) }
    val hasOptionalContent = state.budget?.configured == true || state.form.hasOptionalInput()
    val expanded = showOptional || hasOptionalContent
    BudgetOpenSection(
        title = stringResource(R.string.budget_editor_title),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
    ) {
        if (!state.canModify) {
            Text(
                text = stringResource(R.string.common_readonly_ledger),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
            )
            return@BudgetOpenSection
        }
        val currency = state.formCurrency
        if (currency == null) {
            Text(stringResource(R.string.currency_unconfirmed_write_blocked))
            return@BudgetOpenSection
        }
        CompositionLocalProvider(LocalCurrencyDisplay provides CurrencyDisplay(currency)) {
            MoneyField(
                state = AppAmountInputState(stringResource(R.string.budget_editor_total_label), currency,
                    state.form.totalAmount, stringResource(R.string.budget_editor_total_placeholder),
                    enabled = !state.saving && !state.hasPendingSave),
                onValueChange = actions.onTotalAmountChange,
                modifier = Modifier.testTag("budget_total_amount"),
            )
            if (expanded) {
                Column(modifier = Modifier.testTag("budget_optional_fields"),
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
                    BudgetOptionalAmounts(state, actions)
                    BudgetCategoryFields(state, actions)
                }
            }
        }
        Button(
            modifier = Modifier.fillMaxWidth(),
            enabled = !state.saving && !state.hasPendingSave,
            onClick = actions.onSave,
        ) {
            Text(
                if (state.saving) {
                    stringResource(R.string.common_saving)
                } else {
                    stringResource(R.string.budget_editor_save)
                },
            )
        }
        if (!hasOptionalContent) {
            TextButton(onClick = { showOptional = !showOptional }, modifier = Modifier.testTag("budget_optional_toggle")) {
                Text(stringResource(if (expanded) R.string.budget_editor_optional_hide else R.string.budget_editor_optional_show))
            }
        }
    }
}

@Composable
private fun BudgetOptionalAmounts(
    state: BudgetUiState,
    actions: BudgetEditorActions,
) {
    val enabled = !state.saving && !state.hasPendingSave
    val currency = LocalCurrencyDisplay.current.homeCurrency
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        MoneyField(
            state = AppAmountInputState(stringResource(R.string.budget_editor_rollover_label), currency,
                state.form.rolloverAmount, stringResource(R.string.budget_editor_rollover_placeholder), enabled = enabled),
            onValueChange = actions.onRolloverAmountChange,
            modifier = Modifier.weight(1f),
        )
        MoneyField(
            state = AppAmountInputState(stringResource(R.string.budget_editor_non_monthly_label), currency,
                state.form.nonMonthlyAmount, stringResource(R.string.budget_editor_non_monthly_placeholder), enabled = enabled),
            onValueChange = actions.onNonMonthlyAmountChange,
            modifier = Modifier.weight(1f),
        )
    }
    AppTextInput(
        state = AppTextInputState(
            label = stringResource(R.string.budget_editor_excluded_label),
            value = state.form.excludedCategories,
            placeholder = stringResource(R.string.budget_editor_excluded_placeholder),
            singleLine = false,
            minLines = 1,
            maxLines = 3,
            enabled = enabled,
        ),
        actions = AppTextInputActions(onValueChange = actions.onExcludedCategoriesChange),
        modifier = Modifier.fillMaxWidth(),
    )
}

/** Keep raw draft fields (including invalid input) visible without copying form or error state. */
private fun BudgetFormState.hasOptionalInput(): Boolean =
    rolloverAmount.isNotEmpty() || nonMonthlyAmount.isNotEmpty() || excludedCategories.isNotEmpty() ||
        categoryRows.size > 1 || categoryRows.any { it.category.isNotEmpty() || it.amount.isNotEmpty() }

@Composable
private fun BudgetCategoryFields(
    state: BudgetUiState,
    actions: BudgetEditorActions,
) {
    Text(
        text = stringResource(R.string.budget_editor_category_section_title),
        style = MaterialTheme.typography.titleSmall,
        fontWeight = AppTextHierarchy.body.weight,
    )
    state.form.categoryRows.forEachIndexed { index, row ->
        CategoryInputRow(
            row = row,
            canRemove = state.form.categoryRows.size > 1,
            onChange = { category, amount -> actions.onCategoryRowChange(index, category, amount) },
            onRemove = { actions.onRemoveCategoryRow(index) },
            enabled = !state.saving && !state.hasPendingSave,
        )
    }
    TextButton(onClick = actions.onAddCategoryRow, enabled = !state.saving && !state.hasPendingSave) {
        Icon(Icons.Filled.Add, contentDescription = stringResource(R.string.budget_editor_add_category_description))
        Text(stringResource(R.string.budget_editor_add_category))
    }
}

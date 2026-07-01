package com.ticketbox.ui.screens.budget

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.Button
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.viewmodel.BudgetUiState

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
        BudgetCoreFields(state, actions)
        BudgetCategoryFields(state, actions)
        Button(
            modifier = Modifier.fillMaxWidth(),
            enabled = !state.saving,
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
    }
}

@Composable
private fun BudgetCoreFields(
    state: BudgetUiState,
    actions: BudgetEditorActions,
) {
    MoneyField(
        value = state.form.totalAmount,
        onValueChange = actions.onTotalAmountChange,
        label = stringResource(R.string.budget_editor_total_label),
        placeholder = stringResource(R.string.budget_editor_total_placeholder),
    )
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        MoneyField(
            value = state.form.rolloverAmount,
            onValueChange = actions.onRolloverAmountChange,
            label = stringResource(R.string.budget_editor_rollover_label),
            placeholder = stringResource(R.string.budget_editor_rollover_placeholder),
            modifier = Modifier.weight(1f),
        )
        MoneyField(
            value = state.form.nonMonthlyAmount,
            onValueChange = actions.onNonMonthlyAmountChange,
            label = stringResource(R.string.budget_editor_non_monthly_label),
            placeholder = stringResource(R.string.budget_editor_non_monthly_placeholder),
            modifier = Modifier.weight(1f),
        )
    }
    OutlinedTextField(
        value = state.form.excludedCategories,
        onValueChange = actions.onExcludedCategoriesChange,
        modifier = Modifier.fillMaxWidth(),
        label = { Text(stringResource(R.string.budget_editor_excluded_label)) },
        placeholder = { Text(stringResource(R.string.budget_editor_excluded_placeholder)) },
        minLines = 1,
        maxLines = 3,
    )
}

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
        )
    }
    TextButton(onClick = actions.onAddCategoryRow) {
        Icon(Icons.Filled.Add, contentDescription = stringResource(R.string.budget_editor_add_category_description))
        Text(stringResource(R.string.budget_editor_add_category))
    }
}

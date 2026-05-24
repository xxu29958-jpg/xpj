package com.ticketbox.ui.screens.budget

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
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
import androidx.compose.ui.text.font.FontWeight
import com.ticketbox.ui.components.AppGlassCard
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
internal fun BudgetEditorCard(
    state: BudgetUiState,
    actions: BudgetEditorActions,
) {
    AppGlassCard(containerAlpha = 0.94f) {
        Column(
            modifier = Modifier.padding(AppSpacing.cardPaddingSmall),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
        ) {
            Text(
                text = "预算设置",
                style = MaterialTheme.typography.titleMedium,
                fontWeight = AppTextHierarchy.heading.weight,
            )
            if (!state.canModify) {
                Text(
                    text = "当前角色为只读，无法修改账本。",
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    style = MaterialTheme.typography.bodyMedium,
                )
                return@Column
            }
            BudgetCoreFields(state, actions)
            BudgetCategoryFields(state, actions)
            Button(
                modifier = Modifier.fillMaxWidth(),
                enabled = !state.saving,
                onClick = actions.onSave,
            ) {
                Text(if (state.saving) "保存中" else "保存预算")
            }
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
        label = "月度总预算",
        placeholder = "3000",
    )
    Row(horizontalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
        MoneyField(
            value = state.form.rolloverAmount,
            onValueChange = actions.onRolloverAmountChange,
            label = "结转",
            placeholder = "0",
            modifier = Modifier.weight(1f),
        )
        MoneyField(
            value = state.form.nonMonthlyAmount,
            onValueChange = actions.onNonMonthlyAmountChange,
            label = "非月度预留",
            placeholder = "0",
            modifier = Modifier.weight(1f),
        )
    }
    OutlinedTextField(
        value = state.form.excludedCategories,
        onValueChange = actions.onExcludedCategoriesChange,
        modifier = Modifier.fillMaxWidth(),
        label = { Text("剔除分类") },
        placeholder = { Text("医疗，报销") },
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
        text = "分类预算",
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
        Icon(Icons.Filled.Add, contentDescription = "增加分类预算")
        Text("增加分类")
    }
}

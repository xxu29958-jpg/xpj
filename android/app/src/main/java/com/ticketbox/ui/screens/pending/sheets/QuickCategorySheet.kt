package com.ticketbox.ui.screens.pending.sheets

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.role
import androidx.compose.ui.semantics.selected
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardCapitalization
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.DefaultExpenseCategories
import com.ticketbox.domain.model.isUncategorizedExpenseCategory
import com.ticketbox.ui.components.ExpenseCategoryMark
import com.ticketbox.ui.components.expenseCategorySurface
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppListDensity
import com.ticketbox.ui.design.AppRadius

@Composable
internal fun QuickCategorySheetContent(
    expense: Expense,
    options: List<String>,
    chrome: ReviewSheetChrome,
    onSave: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    val saving = chrome.saving
    val initial = quickCategoryInitialSelection(expense.serverCategory, expense.category)
    val selected = chrome.input.value ?: initial
    val custom = chrome.input.custom

    ReviewSheetScaffold(
        title = stringResource(R.string.quick_category_sheet_title),
        subtitle = stringResource(R.string.quick_category_sheet_hint),
        chrome = chrome,
        actions = {
            ReviewSheetActionFeedback(
                chrome = chrome,
                primary = AppSheetAction(
                    text = if (saving) stringResource(R.string.common_saving) else stringResource(R.string.quick_category_save_button),
                    enabled = !saving && (custom.trim().isNotEmpty() || selected.isNotBlank()),
                    onClick = {
                        val choice = custom.trim().ifBlank { selected }.trim()
                        if (choice.isNotEmpty()) onSave(choice)
                    },
                ),
                secondary = AppSheetAction(
                    text = stringResource(R.string.expense_fact_input_close),
                    enabled = !saving,
                    onClick = onDismiss,
                ),
            )
        },
    ) {
        ReviewExpenseSummary(expense)
        Text(stringResource(R.string.pending_review_current_category, expense.category), style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(stringResource(R.string.pending_category_choose), style = MaterialTheme.typography.titleMedium)
        QuickCategoryOptions(
            options = options,
            selected = selected.takeIf { custom.isBlank() }.orEmpty(),
            enabled = !saving,
            onSelect = {
                chrome.onInputChange(chrome.input.copy(value = it, custom = ""))
            },
        )
        QuickCategoryCustomInput(
            custom = custom,
            saving = saving,
            onCustomChange = { chrome.onInputChange(chrome.input.copy(custom = it.take(20))) },
        )
    }
}

@Composable
private fun QuickCategoryOptions(
    options: List<String>,
    selected: String,
    enabled: Boolean,
    onSelect: (String) -> Unit,
) {
    val primary = listOf(DefaultExpenseCategories.SHOPPING, DefaultExpenseCategories.DINING,
        DefaultExpenseCategories.TRANSIT, DefaultExpenseCategories.HOUSING, DefaultExpenseCategories.MEDICAL,
        DefaultExpenseCategories.OTHER).filter { it in options }
    var expanded by rememberSaveable { mutableStateOf(false) }
    val visible = if (expanded) primary + options.filterNot { it in primary } else primary
    FlowRow(
        modifier = Modifier.fillMaxWidth(), maxItemsInEachRow = 3,
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        visible.forEach { option ->
            Surface(
                onClick = { onSelect(option) }, enabled = enabled,
                modifier = Modifier.weight(1f).widthIn(min = AppSpacing.controlMinHeight * 2 * LocalDensity.current.fontScale.coerceAtLeast(1f))
                    .semantics { this.selected = selected == option; role = Role.RadioButton },
                shape = RoundedCornerShape(AppRadius.medium), color = expenseCategorySurface(option),
                border = if (selected == option) BorderStroke(2.dp, MaterialTheme.colorScheme.primary) else null,
            ) {
                Column(modifier = Modifier.padding(AppSpacing.compactGap), horizontalAlignment = Alignment.CenterHorizontally,
                    verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
                    ExpenseCategoryMark(option, AppListDensity.Standard)
                    Text(option, style = MaterialTheme.typography.labelLarge)
                }
            }
        }
    }
    if (options.any { it !in primary }) TextButton(onClick = { expanded = !expanded }, enabled = enabled) {
        Text(stringResource(if (expanded) R.string.pending_category_less else R.string.pending_category_more))
    }
}

@Composable
private fun QuickCategoryCustomInput(
    custom: String,
    saving: Boolean,
    onCustomChange: (String) -> Unit,
) {
    AppTextInput(
        state = AppTextInputState(
            label = stringResource(R.string.quick_category_custom_label),
            value = custom,
            enabled = !saving,
            keyboardOptions = KeyboardOptions(capitalization = KeyboardCapitalization.None),
        ),
        actions = AppTextInputActions(onValueChange = onCustomChange),
        modifier = Modifier.fillMaxWidth(),
    )
}

// 脏 token（未分类/未分類/none/null，大小写不敏感）不预填：命中值视为空，
// 用户必须主动选择——否则原样保存会把非法 token 写回库（PR #230 round 7）。
// 原始值为空白（展示被归一成「其他」）同样不预填——否则未改即保存会把
// 「其他」写回，未做真实选择就消除了数据质量问题（PR #230 round 10）。
// serverCategory 为 null（无原始值的非新鲜行）回退到展示值判定。
internal fun quickCategoryInitialSelection(serverCategory: String?, displayCategory: String): String {
    if (serverCategory != null && (serverCategory.isBlank() || isUncategorizedExpenseCategory(serverCategory))) {
        return ""
    }
    return displayCategory.takeIf { it.isNotBlank() && !isUncategorizedExpenseCategory(it) }.orEmpty()
}

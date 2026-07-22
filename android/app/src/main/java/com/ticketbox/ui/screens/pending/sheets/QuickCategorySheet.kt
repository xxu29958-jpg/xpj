package com.ticketbox.ui.screens.pending.sheets

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardCapitalization
import com.ticketbox.R
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.isUncategorizedExpenseCategory
import com.ticketbox.ui.components.AppCompactChips
import com.ticketbox.ui.components.AppFilterChip
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.design.AppSpacing

@Composable
internal fun QuickCategorySheetContent(
    expense: Expense,
    options: List<String>,
    chrome: ReviewSheetChrome,
    onSave: (String) -> Unit,
    onDismiss: () -> Unit,
) {
    val saving = chrome.saving
    val initial = quickCategoryInitialSelection(expense.category)
    var selected by remember(expense.id) { mutableStateOf(initial) }
    var custom by remember(expense.id) { mutableStateOf("") }

    ReviewSheetScaffold(
        title = stringResource(R.string.quick_category_sheet_title),
        subtitle = stringResource(R.string.quick_category_sheet_hint),
        chrome = chrome,
    ) {
        QuickCategoryOptions(
            options = options,
            selected = selected,
            custom = custom,
            onSelect = {
                selected = it
                custom = ""
            },
        )
        QuickCategoryCustomInput(
            custom = custom,
            saving = saving,
            onCustomChange = { custom = it.take(20) },
        )

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
                text = stringResource(R.string.common_cancel),
                enabled = !saving,
                onClick = onDismiss,
            ),
        )
    }
}

@Composable
private fun QuickCategoryOptions(
    options: List<String>,
    selected: String,
    custom: String,
    onSelect: (String) -> Unit,
) {
    AppCompactChips {
        FlowRow(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
        ) {
            options.forEach { option ->
                AppFilterChip(
                    label = option,
                    selected = selected == option && custom.isBlank(),
                    onClick = { onSelect(option) },
                )
            }
        }
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
// blank 输入同样回落为空串（保存键禁用，等用户选择）。
internal fun quickCategoryInitialSelection(category: String): String =
    category.takeIf { it.isNotBlank() && !isUncategorizedExpenseCategory(it) }.orEmpty()

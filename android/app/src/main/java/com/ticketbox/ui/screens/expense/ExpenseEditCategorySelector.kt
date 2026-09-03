package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.defaultMinSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import com.ticketbox.R
import com.ticketbox.ui.components.AppCompactChips
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppSheetActionFeedback
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputDecorations
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy

internal const val TAG_CATEGORY_ROW = "expense-edit-category-row"

internal data class ExpenseEditCategorySelectorState(
    val category: String,
    val categories: List<String>,
    val enabled: Boolean,
    val sheetOpen: Boolean,
)

internal data class ExpenseEditCategorySelectorActions(
    val onCategoryChange: (String) -> Unit,
    val onOpenSheet: () -> Unit,
    val onDismissSheet: () -> Unit,
)

/**
 * 分类选择行：当前值一行呈现（真实缺失显「未分类」，不自动伪装成「其他」），
 * 点行进选择 sheet——完整分类网格 + 自定义输入。没有「清除分类」按钮：保存走
 * exclude_unset，空值语义是「保持原值」，不包装一个并不存在的清除命令。
 */
@Composable
internal fun ExpenseEditCategorySelector(
    state: ExpenseEditCategorySelectorState,
    actions: ExpenseEditCategorySelectorActions,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
    ) {
        Text(
            text = stringResource(R.string.expense_edit_category_field_label),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.labelLarge,
            fontWeight = AppTextHierarchy.body.weight,
        )
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .testTag(TAG_CATEGORY_ROW)
                .clickable(
                    enabled = state.enabled,
                    onClickLabel = stringResource(R.string.expense_edit_category_sheet_title),
                    role = Role.Button,
                    onClick = actions.onOpenSheet,
                )
                .defaultMinSize(minHeight = AppSpacing.controlMinHeight),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            val hasCategory = state.category.isNotBlank()
            Text(
                text = if (hasCategory) {
                    state.category
                } else {
                    stringResource(R.string.expense_edit_category_uncategorized)
                },
                modifier = Modifier.weight(1f),
                color = if (hasCategory) {
                    MaterialTheme.colorScheme.onSurface
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                },
                style = MaterialTheme.typography.bodyLarge,
            )
            if (state.enabled) {
                Icon(
                    imageVector = Icons.Filled.ExpandMore,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
    }
    if (state.sheetOpen) {
        ExpenseEditCategorySheet(state = state, actions = actions)
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
private fun ExpenseEditCategorySheet(
    state: ExpenseEditCategorySelectorState,
    actions: ExpenseEditCategorySelectorActions,
) {
    // 当前值不在分类列表里时回填自定义框，便于在原值基础上改；在列表里则从空开始。
    var customText by rememberSaveable {
        mutableStateOf(if (state.category in state.categories) "" else state.category)
    }
    // 带输入的 sheet 不停驻半展开（同 ItemsEditorSheet 等既有惯例）：半展开时
    // IME 会把自定义输入框和确定键一并遮到键盘后，用户看不到正在输入的字。
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = actions.onDismissSheet, sheetState = sheetState) {
        AppSheetScaffold(
            title = stringResource(R.string.expense_edit_category_sheet_title),
            subtitle = stringResource(R.string.expense_edit_category_sheet_subtitle),
        ) {
            if (state.categories.isNotEmpty()) {
                AppCompactChips {
                    FlowRow(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
                        verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap),
                    ) {
                        state.categories.forEach { item ->
                            SelectableCategoryChip(
                                selected = state.category == item,
                                label = item,
                                onClick = {
                                    actions.onCategoryChange(item)
                                    actions.onDismissSheet()
                                },
                            )
                        }
                    }
                }
            }
            AppTextInput(
                state = AppTextInputState(
                    label = stringResource(R.string.expense_edit_category_custom_label),
                    value = customText,
                    placeholder = stringResource(R.string.expense_edit_category_custom_placeholder),
                ),
                actions = AppTextInputActions(onValueChange = { customText = it }),
                modifier = Modifier.fillMaxWidth(),
                decorations = AppTextInputDecorations(),
            )
            AppSheetActionFeedback(
                primary = AppSheetAction(
                    text = stringResource(R.string.common_confirm),
                    enabled = customText.isNotBlank(),
                    onClick = {
                        actions.onCategoryChange(customText.trim())
                        actions.onDismissSheet()
                    },
                ),
                secondary = AppSheetAction(
                    text = stringResource(R.string.common_cancel),
                    onClick = actions.onDismissSheet,
                ),
            )
        }
    }
}

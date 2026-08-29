package com.ticketbox.ui.screens.expense.correction

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.TextButton
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.asString
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppListRow
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.StatusPill
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.expense.ExpenseEditCategoryField
import com.ticketbox.ui.screens.expense.ExpenseEditMerchantField
import com.ticketbox.ui.screens.expense.ExpenseEditNoteField
import com.ticketbox.ui.screens.expense.ExpenseCurrencySelector
import com.ticketbox.ui.screens.expense.ExpenseEditSheetScaffold
import com.ticketbox.viewmodel.ExpenseFactUiState

internal data class ExpenseCorrectionSheetActions(
    val onReasonChange: (String) -> Unit,
    val onMerchantChange: (String) -> Unit,
    val onCategoryChange: (String) -> Unit,
    val onTagsChange: (String) -> Unit,
    val onNoteChange: (String) -> Unit,
    val onAmountChange: (String) -> Unit,
    val onExpenseTimeChange: (String) -> Unit,
    val onCurrencyChange: (com.ticketbox.domain.model.CurrencyCode) -> Unit,
    val onScoreChange: (field: com.ticketbox.viewmodel.CorrectionScoreField, value: Int?) -> Unit,
    val onOpenItems: () -> Unit,
    val onOpenSplits: () -> Unit,
    val onSubmit: () -> Unit,
    val onDismiss: () -> Unit,
)

/**
 * A1 更正组合意图 sheet：reason 居首必填但降层级（一行 helper，不说教）；
 * 基础字段内联编辑；明细/拆账各一个入口行到子 surface，已暂存的变更以
 * 「将随本次更正更新」chip 表达；提交 = 一次 correction intent（标量 +
 * items + splits，只发相对 baseline 变化的部分）。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ExpenseCorrectionSheet(
    state: ExpenseFactUiState,
    canSubmit: Boolean,
    actions: ExpenseCorrectionSheetActions,
) {
    val expense = state.expense ?: return
    ModalBottomSheet(onDismissRequest = actions.onDismiss) {
        ExpenseEditSheetScaffold(
            title = stringResource(R.string.expense_correction_sheet_title),
            subtitle = stringResource(R.string.expense_correction_sheet_subtitle),
        ) {
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
            ) {
                // direct 409 冲突：表单保留，banner 说明（VM 已刷新权威事实）。
                state.correction.conflictMessage?.let { conflict ->
                    AppStatusBanner(
                        message = conflict,
                        tone = MessageTone.Danger,
                        announceUpdates = true,
                    )
                }
                state.correction.submitError?.let { error ->
                    AppStatusBanner(
                        message = error,
                        tone = MessageTone.Danger,
                        announceUpdates = true,
                    )
                }
                CorrectionReasonSection(state = state, actions = actions)
                CorrectionCurrencySection(state = state, actions = actions)
                CorrectionScalarSection(state = state, actions = actions)
                CorrectionScoreSection(state = state, actions = actions)
                CorrectionEntryRow(
                    title = stringResource(R.string.expense_correction_items_entry),
                    touched = state.correction.itemsTouched,
                    enabled = !state.correction.saving && state.expenseItems != null,
                    onClick = actions.onOpenItems,
                )
                CorrectionEntryRow(
                    title = stringResource(R.string.expense_correction_splits_entry),
                    touched = state.correction.splitsTouched,
                    enabled = !state.correction.saving && state.expenseSplits != null,
                    onClick = actions.onOpenSplits,
                )
                AppSheetActionRow(
                    primary = AppSheetAction(
                        text = if (state.correction.saving) {
                            stringResource(R.string.expense_correction_saving)
                        } else {
                            stringResource(R.string.expense_correction_submit)
                        },
                        enabled = canSubmit,
                        onClick = actions.onSubmit,
                    ),
                )
            }
        }
    }
}

/** reason：必填但降层级 —— 一句话 helper，提交禁用态承担约束表达。 */
@Composable
private fun CorrectionReasonSection(
    state: ExpenseFactUiState,
    actions: ExpenseCorrectionSheetActions,
) {
    val form = state.correction
    AppTextInput(
        state = AppTextInputState(
            label = stringResource(R.string.expense_correction_reason_label),
            value = form.reason,
            placeholder = stringResource(R.string.expense_correction_reason_placeholder),
            enabled = !form.saving,
        ),
        actions = AppTextInputActions(onValueChange = actions.onReasonChange),
        modifier = Modifier.fillMaxWidth(),
    )
    Text(
        text = stringResource(R.string.expense_correction_reason_helper),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodySmall,
    )
}

@Composable
private fun CorrectionScalarSection(
    state: ExpenseFactUiState,
    actions: ExpenseCorrectionSheetActions,
) {
    val expense = state.expense ?: return
    val form = state.correction
    CorrectionAmountSection(state = state, actions = actions)
    ExpenseEditMerchantField(
        merchant = form.merchant,
        onMerchantChange = actions.onMerchantChange,
        enabled = !form.saving,
    )
    ExpenseEditCategoryField(
        category = form.category,
        categories = state.categories,
        onCategoryChange = actions.onCategoryChange,
        enabled = !form.saving,
    )
    AppTextInput(
        state = AppTextInputState(
            label = stringResource(R.string.expense_correction_tags_label),
            value = form.tags,
            placeholder = stringResource(R.string.expense_correction_tags_placeholder),
            enabled = !form.saving,
        ),
        actions = AppTextInputActions(onValueChange = actions.onTagsChange),
        modifier = Modifier.fillMaxWidth(),
    )
    CorrectionTimeSection(state = state, actions = actions)
    ExpenseEditNoteField(
        note = form.note,
        onNoteChange = actions.onNoteChange,
        enabled = !form.saving,
    )
}

/** 币种：未知原币只阻断金额（选支持币种后可继续），其他字段不受影响；
 *  支持外币时告知本位币自动重算。 */
@Composable
private fun CorrectionCurrencySection(
    state: ExpenseFactUiState,
    actions: ExpenseCorrectionSheetActions,
) {
    val form = state.correction
    form.unsupportedCurrencyCode?.let { raw ->
        Text(
            text = stringResource(R.string.expense_correction_currency_unsupported_hint, raw),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
    ExpenseCurrencySelector(
        currency = form.currency,
        enabled = !form.saving,
        onCurrencySelect = actions.onCurrencyChange,
    )
    if (form.foreignCurrency || form.currencyTouched && form.unsupportedCurrencyCode != null) {
        Text(
            text = stringResource(R.string.expense_correction_currency_foreign),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

/** 两个 1..5 可清空评分：点同值=清除，点「清除」=清空；空值即清空语义。 */
@Composable
private fun CorrectionScoreSection(
    state: ExpenseFactUiState,
    actions: ExpenseCorrectionSheetActions,
) {
    AppSectionHeader(title = stringResource(R.string.expense_fact_field_score))
    CorrectionScoreRow(
        label = stringResource(R.string.expense_correction_score_value),
        value = state.correction.valueScore,
        enabled = !state.correction.saving,
        onSelect = { actions.onScoreChange(com.ticketbox.viewmodel.CorrectionScoreField.Value, it) },
    )
    CorrectionScoreRow(
        label = stringResource(R.string.expense_correction_score_regret),
        value = state.correction.regretScore,
        enabled = !state.correction.saving,
        onSelect = { actions.onScoreChange(com.ticketbox.viewmodel.CorrectionScoreField.Regret, it) },
    )
}

@Composable
private fun CorrectionScoreRow(
    label: String,
    value: Int?,
    enabled: Boolean,
    onSelect: (Int?) -> Unit,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            text = label,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.weight(1f),
        )
        (1..5).forEach { score ->
            FilterChip(
                selected = value == score,
                onClick = { onSelect(if (value == score) null else score) },
                label = { Text(text = score.toString()) },
                enabled = enabled,
            )
        }
        if (value != null) {
            TextButton(
                onClick = { onSelect(null) },
                enabled = enabled,
            ) {
                Text(text = stringResource(R.string.expense_correction_score_clear))
            }
        }
    }
}

@Composable
private fun CorrectionEntryRow(
    title: String,
    touched: Boolean,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    AppListRow(
        onClick = if (enabled) onClick else null,
    ) {
        Text(
            text = title,
            color = if (enabled) {
                MaterialTheme.colorScheme.onSurface
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
            style = MaterialTheme.typography.bodyLarge,
            modifier = Modifier.weight(1f),
        )
        if (touched) {
            StatusPill(
                text = stringResource(R.string.expense_correction_section_pending_change),
                active = false,
            )
        }
    }
}

@Composable
private fun CorrectionAmountSection(
    state: ExpenseFactUiState,
    actions: ExpenseCorrectionSheetActions,
) {
    val expense = state.expense ?: return
    val form = state.correction
    val amountBlocked = form.unsupportedCurrencyCode != null && !form.currencyTouched
    AppSectionHeader(title = stringResource(R.string.expense_fact_field_amount))
    AppTextInput(
        state = AppTextInputState(
            label = stringResource(
                R.string.expense_correction_amount_label,
                if (form.currencyTouched) form.currency.storageKey else expense.originalCurrencyCode,
            ),
            value = form.amountText,
            enabled = !form.saving && !amountBlocked,
        ),
        actions = AppTextInputActions(onValueChange = actions.onAmountChange),
        modifier = Modifier.fillMaxWidth(),
    )
    form.amountError?.let { error ->
        Text(
            text = error.asString(),
            color = MaterialTheme.colorScheme.error,
            style = MaterialTheme.typography.bodySmall,
        )
    }
}

@Composable
private fun CorrectionTimeSection(
    state: ExpenseFactUiState,
    actions: ExpenseCorrectionSheetActions,
) {
    val form = state.correction
    AppTextInput(
        state = AppTextInputState(
            label = stringResource(R.string.expense_correction_time_label),
            value = form.expenseTimeText,
            placeholder = stringResource(R.string.expense_correction_time_placeholder),
            enabled = !form.saving,
        ),
        actions = AppTextInputActions(onValueChange = actions.onExpenseTimeChange),
        modifier = Modifier.fillMaxWidth(),
    )
    form.timeError?.let { error ->
        Text(
            text = error.asString(),
            color = MaterialTheme.colorScheme.error,
            style = MaterialTheme.typography.bodySmall,
        )
    }
    Text(
        text = stringResource(R.string.expense_correction_time_helper),
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        style = MaterialTheme.typography.bodySmall,
    )
}

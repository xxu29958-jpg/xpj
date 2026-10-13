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
import androidx.compose.material3.SheetValue
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.ui.screens.expense.toSavedJson
import com.ticketbox.R
import com.ticketbox.ui.asString
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.ui.components.AppContentCard
import com.ticketbox.ui.components.AppSectionHeader
import com.ticketbox.ui.components.AppSheetAction
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.components.AppSheetActionRow
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.expense.ExpenseEditCategoryField
import com.ticketbox.ui.screens.expense.ExpenseEditMerchantField
import com.ticketbox.ui.screens.expense.ExpenseEditNoteField
import com.ticketbox.ui.screens.expense.ExpenseCurrencySelector
import com.ticketbox.ui.screens.expense.ExpenseEditSheetScaffold
import com.ticketbox.viewmodel.ExpenseCorrectionAvailability
import com.ticketbox.viewmodel.ExpenseFactUiState
import com.ticketbox.viewmodel.CorrectionReviewSelection
import com.ticketbox.viewmodel.currentCorrectionItems
import com.ticketbox.viewmodel.currentCorrectionSplits
import com.ticketbox.ui.screens.settings.SettingsEntryRow
import com.ticketbox.ui.screens.settings.SettingsEntryRowOptions

internal data class ExpenseCorrectionSheetActions(
    val onReasonChange: (String) -> Unit,
    val onMerchantChange: (String) -> Unit,
    val onCategoryChange: (String) -> Unit,
    val onTagsChange: (String) -> Unit,
    val onNoteChange: (String) -> Unit,
    val onAmountChange: (String) -> Unit,
    val onExpenseTimeChange: (String) -> Unit,
    val onTimeFormChange: (String) -> Unit,
    val onCurrencyChange: (com.ticketbox.domain.model.CurrencyCode) -> Unit,
    val onScoreChange: (field: com.ticketbox.viewmodel.CorrectionScoreField, value: Int?) -> Unit,
    val onOpenItems: () -> Unit,
    val onOpenSplits: () -> Unit,
    val onRefreshFact: () -> Unit,
    val onReview: (CorrectionReviewSelection) -> Unit,
    val onRetryInputSave: () -> Unit,
    val onSubmit: () -> Unit,
    val onDismiss: () -> Unit,
)

/**
 * 更正先对照当前记录与本次修改，原因必填；各分项继续由原更正任务保存。
 * 展开状态只负责阅读层级，输入、基线与提交仍归既有 ViewModel。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ExpenseCorrectionSheet(
    state: ExpenseFactUiState,
    basis: com.ticketbox.domain.model.Expense,
    availability: ExpenseCorrectionAvailability,
    actions: ExpenseCorrectionSheetActions,
) {
    if (state.expense == null) return
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true,
        confirmValueChange = { target -> !state.correction.saving || target != SheetValue.Hidden })
    ModalBottomSheet(onDismissRequest = actions.onDismiss, sheetState = sheetState) {
        ExpenseEditSheetScaffold(
            title = stringResource(R.string.expense_correction_sheet_title),
            subtitle = stringResource(R.string.expense_correction_sheet_subtitle),
            actions = {
                (state.correction.submitError ?: availability.contextError.takeIf { availability.review == null })?.let { error ->
                    AppStatusBanner(
                        message = error,
                        tone = MessageTone.Danger,
                        announceUpdates = true,
                    )
                }
                com.ticketbox.ui.screens.expense.fact.FactInputSaveStatus(state, actions.onRetryInputSave)
                AppSheetActionRow(
                    primary = AppSheetAction(
                        text = if (state.correction.saving) {
                            stringResource(R.string.expense_correction_saving)
                        } else {
                            stringResource(R.string.expense_correction_submit)
                        },
                        enabled = availability.canSubmit,
                        onClick = actions.onSubmit,
                    ),
                    secondary = AppSheetAction(text = stringResource(R.string.expense_fact_input_close),
                        enabled = !state.correction.saving, onClick = actions.onDismiss),
                )
            },
        ) {
            CorrectionFormContent(state, basis, availability, actions)
        }
    }
}

@Composable
private fun CorrectionFormContent(state: ExpenseFactUiState, basis: com.ticketbox.domain.model.Expense,
    availability: ExpenseCorrectionAvailability, actions: ExpenseCorrectionSheetActions) {
    var fieldsExpanded by remember(basis.id) { mutableStateOf(true) }
    LaunchedEffect(availability.review?.current?.rowVersion) {
        if (availability.review?.current?.rowVersion?.let { it != basis.rowVersion } == true) fieldsExpanded = false
    }
    LaunchedEffect(state.correction.amountError, state.correction.timeError) {
        if (state.correction.amountError != null || state.correction.timeError != null) fieldsExpanded = true
    }
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
        availability.review?.let { CorrectionReviewPanel(it, state, actions.onReview, actions.onRefreshFact) }
        val inputState = state.copy(expense = basis,
            correction = state.correction.copy(saving = state.correction.saving || !availability.canEditInput))
        CorrectionReasonSection(state = inputState, actions = actions)
        SettingsEntryRow(title = stringResource(R.string.expense_correction_fields_title),
            subtitle = stringResource(R.string.expense_correction_fields_hint), icon = R.drawable.ic_lucide_receipt_text,
            onClick = { fieldsExpanded = !fieldsExpanded }, options = SettingsEntryRowOptions(expanded = fieldsExpanded))
        if (fieldsExpanded) {
            CorrectionCurrencySection(state = inputState, actions = actions)
            CorrectionScalarSection(state = inputState, actions = actions)
            CorrectionScoreSection(state = inputState, actions = actions)
            TextButton(onClick = { fieldsExpanded = false }) { Text(stringResource(R.string.expense_correction_preview)) }
        }
        // Live comparisons grow as fields change; keep them after the editor so typing cannot push its focus off-screen.
        if (availability.review == null) {
            com.ticketbox.viewmodel.correctionScalarComparisons(basis, basis, state.correction).forEach {
                CorrectionComparison(it)
            }
        }
        AppContentCard { CorrectionCollectionEntries(state, availability, actions) }
    }
}

@Composable
private fun CorrectionCollectionEntries(
    state: ExpenseFactUiState,
    availability: ExpenseCorrectionAvailability,
    actions: ExpenseCorrectionSheetActions,
) {
    CorrectionEntryRow(
        title = stringResource(R.string.expense_correction_items_entry),
        icon = R.drawable.ic_lucide_receipt_text,
        touched = state.correction.itemsTouched,
        enabled = !state.correction.saving && availability.canEditItems,
        onClick = actions.onOpenItems,
    )
    CorrectionEntryRow(
        title = stringResource(R.string.expense_correction_splits_entry),
        icon = R.drawable.ic_lucide_users,
        touched = state.correction.splitsTouched,
        enabled = !state.correction.saving && availability.canEditSplits,
        onClick = actions.onOpenSplits,
    )
    if (availability.contextError == null && (state.currentCorrectionItems == null || state.currentCorrectionSplits == null)) {
        Text(
            text = stringResource(R.string.expense_correction_collections_not_current),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        TextButton(
            enabled = !state.expenseLoading && !state.itemsLoading && !state.splitsLoading,
            onClick = actions.onRefreshFact,
        ) {
            Text(stringResource(R.string.expense_fact_refresh_current))
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
    icon: Int,
    touched: Boolean,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    SettingsEntryRow(title = title, icon = icon,
        subtitle = if (touched) stringResource(R.string.expense_correction_section_pending_change)
            else stringResource(R.string.expense_correction_collection_hint),
        onClick = if (enabled) onClick else null,
    )
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
    val expense = state.expense ?: return
    val (initial, setInitial) = com.ticketbox.ui.screens.expense.rememberExpenseTimeForm(
        expense.id, expense.expenseTime, expense.accountingTime, form.timeFormJson,
    )
    val captured = com.ticketbox.ui.screens.expense.readExpenseTimeForm(form.timeFormJson) ?: initial
    com.ticketbox.ui.screens.expense.ExpenseTimeEditor(captured, {
        setInitial(it)
        actions.onTimeFormChange(it.toSavedJson())
    }, !form.saving)
    if (expense.expenseTime != null) TextButton(enabled = !form.saving, onClick = {
        setInitial(captured.copy(date = "", time = "", originalInstant = null, offsetSeconds = null, changed = false))
        actions.onExpenseTimeChange("")
    }) { Text(stringResource(R.string.calendar_input_clear_instant)) }
    if (form.expenseTimeText.isBlank() && form.timeFormJson == null && expense.expenseTime != null) {
        Text(stringResource(R.string.calendar_input_instant_cleared), style = MaterialTheme.typography.bodySmall)
    }
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

package com.ticketbox.ui.screens.expense

import com.ticketbox.ui.screens.settings.SettingsEntryRowOptions
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.SheetValue
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.ExpenseItemKind
import com.ticketbox.ui.components.AppAdaptiveFieldPairRow
import com.ticketbox.ui.components.AppAdaptiveFieldPairWeights
import com.ticketbox.ui.components.AppSegmentedControl
import com.ticketbox.ui.components.AppSegmentedItem
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.components.parseAmountCentsForDisplay
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.EditableItem
import com.ticketbox.ui.components.AppSheetActionFeedbackState
import com.ticketbox.ui.screens.settings.SettingsEntryRow
import kotlin.math.abs

data class ItemsEditorSheetState(
    val drafts: List<EditableItem>,
    val parentAmountCents: Long?,
    val saving: Boolean,
    // 票据 record 口径的 display context（R14-1）：footer 合计解析与保存侧同源（零小数
    //  home 不 ×100；未知码经 forRecord 原样亮码+原 minor，不冒枚举兜底符号）。
    val display: CurrencyDisplay = CurrencyDisplay.Base,
    val feedback: AppSheetActionFeedbackState = AppSheetActionFeedbackState(),
    val primaryText: String? = null,
    val subtitle: String? = null,
)

data class ItemsEditorSheetActions(
    val onUpdate: (index: Int, name: String?, amountText: String?, kind: String?) -> Unit,
    val onAddRow: () -> Unit,
    val onRemoveRow: (index: Int) -> Unit,
    val onSave: () -> Unit,
    val onDismiss: () -> Unit,
)

// ADR-0044 wave 2: the label is held as a @StringRes id (resolved in the composable
// via stringResource) so this top-level table stays string-resource-backed without a
// Context here. The kind key (.first) is the ADR-0035 enum value, not user-visible.
private val ITEM_KINDS: List<Pair<String, Int>> = listOf(
    ExpenseItemKind.PRODUCT to R.string.expense_edit_items_kind_product,
    ExpenseItemKind.DISCOUNT to R.string.expense_edit_items_kind_discount,
    ExpenseItemKind.TAX to R.string.expense_edit_items_kind_tax,
    ExpenseItemKind.SERVICE_FEE to R.string.expense_edit_items_kind_service_fee,
)

private val ITEM_FIELD_WEIGHTS = AppAdaptiveFieldPairWeights(leading = 1.35f, trailing = 1f)

private fun draftSignedCents(draft: EditableItem, display: CurrencyDisplay): Long? {
    // R15b-2：未知码按原 minor 整数解析（display 口径），不按兜底枚举放大 100×。
    val magnitude = parseAmountCentsForDisplay(draft.amountText, display) ?: return null
    return if (draft.kind == ExpenseItemKind.DISCOUNT) -abs(magnitude) else magnitude
}

/**
 * PR-D items editor. A full-height [ModalBottomSheet] of editable line-item rows
 * with scrolling reconciliation (明细合计 / 账单金额 / 差额) and fixed task actions. Each row carries a name,
 * an amount (magnitude in yuan), a kind segmented control, and a delete action;
 * "添加项目" appends a blank row. Save is never blocked on a mismatch — a receipt
 * may legitimately not reconcile, so the difference is surfaced as quiet status.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ItemsEditorSheet(
    state: ItemsEditorSheetState,
    actions: ItemsEditorSheetActions,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true,
        confirmValueChange = { target -> !state.saving || target != SheetValue.Hidden })
    ModalBottomSheet(onDismissRequest = { if (!state.saving) actions.onDismiss() }, sheetState = sheetState) {
        ExpenseEditSheetScaffold(
            title = stringResource(R.string.expense_edit_items_sheet_title),
            subtitle = state.subtitle ?: stringResource(R.string.expense_edit_items_sheet_subtitle),
            actions = {
                ExpenseEditSheetActions(
                    state = ExpenseEditSheetActionState(
                        saving = state.saving,
                        primaryEnabled = true,
                        savingText = stringResource(R.string.expense_edit_items_saving_button),
                        primaryText = state.primaryText ?: stringResource(R.string.expense_edit_items_save_button),
                        secondaryText = stringResource(R.string.expense_edit_subtask_back),
                        feedback = state.feedback,
                    ),
                    handlers = ExpenseEditSheetActionHandlers(
                        onDismiss = actions.onDismiss,
                        onSubmit = actions.onSave,
                    ),
                )
            },
        ) {
            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            ) {
                state.drafts.forEachIndexed { index, draft ->
                    ItemEditorRow(
                        index = index,
                        draft = draft,
                        display = state.display,
                        actions = actions,
                        enabled = !state.saving,
                    )
                }
                ExpenseDetailActionButtonRow(
                    text = stringResource(R.string.expense_edit_items_add_row_button),
                    icon = Icons.Filled.Add,
                    enabled = !state.saving,
                    onClick = actions.onAddRow,
                )
            }

            ReconciliationFooter(
                drafts = state.drafts,
                parentAmountCents = state.parentAmountCents,
                display = state.display,
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ItemEditorRow(
    index: Int,
    draft: EditableItem,
    display: CurrencyDisplay,
    actions: ItemsEditorSheetActions,
    enabled: Boolean,
) {
    var expanded by rememberSaveable { mutableStateOf(draft.name.isBlank()) }
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        SettingsEntryRow(
            title = draft.name.ifBlank { stringResource(R.string.expense_edit_items_row_new) },
            subtitle = ITEM_KINDS.firstOrNull { it.first == draft.kind }?.let { stringResource(it.second) } ?: draft.kind,
            icon = R.drawable.ic_lucide_shopping_bag,
            onClick = { if (enabled) expanded = !expanded },
            options = SettingsEntryRowOptions(
                amount = draftSignedCents(draft, display)?.let { formatDisplayAmount(it, display) }
                    ?: draft.amountText.ifBlank { stringResource(R.string.expense_edit_items_amount_empty) },
                expanded = expanded, modifier = Modifier.testTag("expense-item-editor-$index"),
            ),
        )
        if (expanded) {
            AppAdaptiveFieldPairRow(
                weights = ITEM_FIELD_WEIGHTS,
                leading = { fieldModifier ->
                    ItemNameField(
                        index = index,
                        draft = draft,
                        onUpdate = actions.onUpdate,
                        enabled = enabled,
                        modifier = fieldModifier,
                    )
                },
                trailing = { fieldModifier ->
                    ItemAmountField(
                        index = index,
                        draft = draft,
                        onUpdate = actions.onUpdate,
                        enabled = enabled,
                        modifier = fieldModifier,
                    )
                },
                action = { ItemRemoveButton(onRemove = { actions.onRemoveRow(index) }, enabled = enabled) },
            )
            Text(
                text = stringResource(R.string.expense_edit_items_row_kind_label),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            AppSegmentedControl(
                options = ITEM_KINDS.map { pair ->
                    AppSegmentedItem(pair.first, stringResource(pair.second), enabled = enabled)
                },
                selectedValue = draft.kind,
                onValueChange = { actions.onUpdate(index, null, null, it) },
            )
        }
    }
}

@Composable
private fun ItemNameField(
    index: Int,
    draft: EditableItem,
    onUpdate: (index: Int, name: String?, amountText: String?, kind: String?) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean,
) {
    ExpenseEditTextField(
        state = ExpenseEditTextFieldState(
            label = stringResource(R.string.expense_edit_items_row_name_label),
            value = draft.name,
            enabled = enabled,
            placeholder = stringResource(R.string.expense_edit_items_row_name_placeholder),
        ),
        onValueChange = { onUpdate(index, it, null, null) },
        modifier = modifier,
    )
}

@Composable
private fun ItemAmountField(
    index: Int,
    draft: EditableItem,
    onUpdate: (index: Int, name: String?, amountText: String?, kind: String?) -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean,
) {
    ExpenseEditTextField(
        state = ExpenseEditTextFieldState(
            label = stringResource(R.string.expense_edit_items_row_amount_label),
            value = draft.amountText,
            enabled = enabled,
            placeholder = stringResource(R.string.components_amount_input_placeholder),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        ),
        onValueChange = { onUpdate(index, null, it, null) },
        modifier = modifier,
        fieldModifier = Modifier.testTag("expense-item-amount-$index"),
    )
}

@Composable
private fun ItemRemoveButton(onRemove: () -> Unit, enabled: Boolean) {
    IconButton(onClick = onRemove, enabled = enabled) {
        Icon(
            Icons.Filled.Close,
            contentDescription = stringResource(R.string.expense_edit_items_row_remove_desc),
            tint = MaterialTheme.colorScheme.error,
        )
    }
}

@Composable
private fun ReconciliationFooter(
    drafts: List<EditableItem>,
    parentAmountCents: Long?,
    display: CurrencyDisplay,
) {
    // 显示与保存/解析同源于票据 record 币种（JPY 零小数整数显示整数；未知码亮原码+原
    // minor，R14-1），不读恒 Base 的 LocalCurrencyDisplay（PR#255 P1）。R15b-2：未知码
    // 草稿金额按原 minor 整数解析（与回填/显示同空间，不按兜底枚举放大 100×）。
    val amounts = drafts.filter { it.name.isNotBlank() || it.amountText.isNotBlank() }.map { draftSignedCents(it, display) }
    val total = if (amounts.any { it == null }) null else amounts.filterNotNull().sum()
    val diff = parentAmountCents?.let { parent -> total?.minus(parent) }
    ExpenseEditReconciliationRows(
        rows = listOfNotNull(
            ExpenseEditReconciliationLine(
                label = stringResource(R.string.expense_edit_items_footer_total_label),
                value = formatDisplayAmount(total, display),
            ),
            parentAmountCents?.let {
                ExpenseEditReconciliationLine(
                    label = stringResource(R.string.expense_edit_items_footer_bill_label),
                    value = formatDisplayAmount(it, display),
                )
            },
            diff?.takeIf { it != 0L }?.let {
                ExpenseEditReconciliationLine(
                    label = stringResource(R.string.expense_edit_items_footer_diff_label),
                    value = formatDisplayAmount(it, display),
                    emphasis = true,
                )
            },
        ),
    )
}

package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseItemKind
import com.ticketbox.domain.model.FxContract
import com.ticketbox.ui.components.AppAdaptiveFieldPairRow
import com.ticketbox.ui.components.AppAdaptiveFieldPairWeights
import com.ticketbox.ui.components.AppSegmentedControl
import com.ticketbox.ui.components.AppSegmentedItem
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalCurrencyDisplay
import com.ticketbox.viewmodel.EditableItem
import kotlin.math.abs

data class ItemsEditorSheetState(
    val drafts: List<EditableItem>,
    val parentAmountCents: Long?,
    val saving: Boolean,
    // 票据的服务端 home 币种：footer 合计解析与保存侧同口径（零小数 home 不 ×100）。
    val currency: CurrencyCode = FxContract.HomeCurrency,
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

private fun draftSignedCents(draft: EditableItem, currency: CurrencyCode): Long {
    val magnitude = parseAmountCents(draft.amountText, currency) ?: 0L
    return if (draft.kind == ExpenseItemKind.DISCOUNT) -abs(magnitude) else magnitude
}

/**
 * PR-D items editor. A full-height [ModalBottomSheet] of editable line-item rows
 * with a pinned reconciliation footer (明细合计 / 账单金额 / 差额). Each row carries a name,
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
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = actions.onDismiss, sheetState = sheetState) {
        ExpenseEditSheetScaffold(
            title = stringResource(R.string.expense_edit_items_sheet_title),
            subtitle = stringResource(R.string.expense_edit_items_sheet_subtitle),
        ) {
            LazyColumn(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = AppSpacing.controlMinHeight * 7),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            ) {
                itemsIndexed(state.drafts) { index, draft ->
                    ItemEditorRow(
                        index = index,
                        draft = draft,
                        onUpdate = actions.onUpdate,
                        onRemove = { actions.onRemoveRow(index) },
                    )
                }
                item {
                    ExpenseDetailActionButtonRow(
                        text = stringResource(R.string.expense_edit_items_add_row_button),
                        icon = Icons.Filled.Add,
                        onClick = actions.onAddRow,
                    )
                }
            }

            ReconciliationFooter(
                drafts = state.drafts,
                parentAmountCents = state.parentAmountCents,
                currency = state.currency,
            )
            ExpenseEditSheetActions(
                state = ExpenseEditSheetActionState(
                    saving = state.saving,
                    primaryEnabled = true,
                    savingText = stringResource(R.string.expense_edit_items_saving_button),
                    primaryText = stringResource(R.string.expense_edit_items_save_button),
                ),
                handlers = ExpenseEditSheetActionHandlers(
                    onDismiss = actions.onDismiss,
                    onSubmit = actions.onSave,
                ),
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun ItemEditorRow(
    index: Int,
    draft: EditableItem,
    onUpdate: (index: Int, name: String?, amountText: String?, kind: String?) -> Unit,
    onRemove: () -> Unit,
) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        AppAdaptiveFieldPairRow(
            weights = ITEM_FIELD_WEIGHTS,
            leading = { fieldModifier ->
                ItemNameField(
                    index = index,
                    draft = draft,
                    onUpdate = onUpdate,
                    modifier = fieldModifier,
                )
            },
            trailing = { fieldModifier ->
                ItemAmountField(
                    index = index,
                    draft = draft,
                    onUpdate = onUpdate,
                    modifier = fieldModifier,
                )
            },
            action = { ItemRemoveButton(onRemove = onRemove) },
        )
        Text(
            text = stringResource(R.string.expense_edit_items_row_kind_label),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        AppSegmentedControl(
            options = ITEM_KINDS.map { pair ->
                AppSegmentedItem(pair.first, stringResource(pair.second))
            },
            selectedValue = draft.kind,
            onValueChange = { onUpdate(index, null, null, it) },
        )
    }
}

@Composable
private fun ItemNameField(
    index: Int,
    draft: EditableItem,
    onUpdate: (index: Int, name: String?, amountText: String?, kind: String?) -> Unit,
    modifier: Modifier = Modifier,
) {
    ExpenseEditTextField(
        state = ExpenseEditTextFieldState(
            label = stringResource(R.string.expense_edit_items_row_name_label),
            value = draft.name,
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
) {
    ExpenseEditTextField(
        state = ExpenseEditTextFieldState(
            label = stringResource(R.string.expense_edit_items_row_amount_label),
            value = draft.amountText,
            placeholder = stringResource(R.string.components_amount_input_placeholder),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        ),
        onValueChange = { onUpdate(index, null, it, null) },
        modifier = modifier,
    )
}

@Composable
private fun ItemRemoveButton(onRemove: () -> Unit) {
    IconButton(onClick = onRemove) {
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
    currency: CurrencyCode,
) {
    val currencyDisplay = LocalCurrencyDisplay.current
    val total = drafts.sumOf { draftSignedCents(it, currency) }
    val diff = parentAmountCents?.let { total - it }
    ExpenseEditReconciliationRows(
        rows = listOfNotNull(
            ExpenseEditReconciliationLine(
                label = stringResource(R.string.expense_edit_items_footer_total_label),
                value = formatDisplayAmount(total, currencyDisplay),
            ),
            parentAmountCents?.let {
                ExpenseEditReconciliationLine(
                    label = stringResource(R.string.expense_edit_items_footer_bill_label),
                    value = formatDisplayAmount(it, currencyDisplay),
                )
            },
            diff?.takeIf { it != 0L }?.let {
                ExpenseEditReconciliationLine(
                    label = stringResource(R.string.expense_edit_items_footer_diff_label),
                    value = formatDisplayAmount(it, currencyDisplay),
                    emphasis = true,
                )
            },
        ),
    )
}

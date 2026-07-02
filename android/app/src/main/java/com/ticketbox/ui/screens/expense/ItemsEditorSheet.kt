package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.width
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
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.domain.model.ExpenseItemKind
import com.ticketbox.ui.components.AppSegmentedControl
import com.ticketbox.ui.components.AppSegmentedItem
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.EditableItem
import kotlin.math.abs

// ADR-0044 wave 2: the label is held as a @StringRes id (resolved in the composable
// via stringResource) so this top-level table stays string-resource-backed without a
// Context here. The kind key (.first) is the ADR-0035 enum value, not user-visible.
private val ITEM_KINDS: List<Pair<String, Int>> = listOf(
    ExpenseItemKind.PRODUCT to R.string.expense_edit_items_kind_product,
    ExpenseItemKind.DISCOUNT to R.string.expense_edit_items_kind_discount,
    ExpenseItemKind.TAX to R.string.expense_edit_items_kind_tax,
    ExpenseItemKind.SERVICE_FEE to R.string.expense_edit_items_kind_service_fee,
)

private fun draftSignedCents(draft: EditableItem): Long {
    val magnitude = parseAmountCents(draft.amountText) ?: 0L
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
    drafts: List<EditableItem>,
    parentAmountCents: Long?,
    saving: Boolean,
    onUpdate: (index: Int, name: String?, amountText: String?, kind: String?) -> Unit,
    onAddRow: () -> Unit,
    onRemoveRow: (index: Int) -> Unit,
    onSave: () -> Unit,
    onDismiss: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
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
                itemsIndexed(drafts) { index, draft ->
                    ItemEditorRow(
                        index = index,
                        draft = draft,
                        onUpdate = onUpdate,
                        onRemove = { onRemoveRow(index) },
                    )
                }
                item {
                    TextButton(onClick = onAddRow) {
                        Icon(Icons.Filled.Add, contentDescription = null)
                        Spacer(Modifier.width(AppSpacing.tinyGap))
                        Text(stringResource(R.string.expense_edit_items_add_row_button))
                    }
                }
            }

            ReconciliationFooter(drafts = drafts, parentAmountCents = parentAmountCents)
            ExpenseEditSheetActions(
                state = ExpenseEditSheetActionState(
                    saving = saving,
                    primaryEnabled = true,
                    savingText = stringResource(R.string.expense_edit_items_saving_button),
                    primaryText = stringResource(R.string.expense_edit_items_save_button),
                ),
                handlers = ExpenseEditSheetActionHandlers(
                    onDismiss = onDismiss,
                    onSubmit = onSave,
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
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            ExpenseEditTextField(
                state = ExpenseEditTextFieldState(
                    label = stringResource(R.string.expense_edit_items_row_name_label),
                    value = draft.name,
                    placeholder = stringResource(R.string.expense_edit_items_row_name_placeholder),
                ),
                onValueChange = { onUpdate(index, it, null, null) },
                modifier = Modifier.weight(1.35f),
            )
            ExpenseEditTextField(
                state = ExpenseEditTextFieldState(
                    label = stringResource(R.string.expense_edit_items_row_amount_label),
                    value = draft.amountText,
                    placeholder = stringResource(R.string.components_amount_input_placeholder),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                ),
                onValueChange = { onUpdate(index, null, it, null) },
                modifier = Modifier.weight(1f),
            )
            IconButton(onClick = onRemove) {
                Icon(
                    Icons.Filled.Close,
                    contentDescription = stringResource(R.string.expense_edit_items_row_remove_desc),
                    tint = MaterialTheme.colorScheme.error,
                )
            }
        }
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
private fun ReconciliationFooter(
    drafts: List<EditableItem>,
    parentAmountCents: Long?,
) {
    val total = drafts.sumOf { draftSignedCents(it) }
    val diff = parentAmountCents?.let { total - it }
    ExpenseEditReconciliationRows(
        rows = listOfNotNull(
            ExpenseEditReconciliationLine(
                label = stringResource(R.string.expense_edit_items_footer_total_label),
                value = formatDisplayAmount(total),
            ),
            parentAmountCents?.let {
                ExpenseEditReconciliationLine(
                    label = stringResource(R.string.expense_edit_items_footer_bill_label),
                    value = formatDisplayAmount(it),
                )
            },
            diff?.takeIf { it != 0L }?.let {
                ExpenseEditReconciliationLine(
                    label = stringResource(R.string.expense_edit_items_footer_diff_label),
                    value = formatDisplayAmount(it),
                    emphasis = true,
                )
            },
        ),
    )
}

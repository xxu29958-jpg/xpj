package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.ExpenseItemKind
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.components.parseAmountCents
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
 * with a pinned reconciliation footer (合计 / 票面 / 差额). Each row carries a name,
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
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .navigationBarsPadding(),
        ) {
            Text(stringResource(R.string.expense_edit_items_sheet_title), style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(4.dp))
            Text(
                stringResource(R.string.expense_edit_items_sheet_subtitle),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(12.dp))

            LazyColumn(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 380.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
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
                        Spacer(Modifier.width(6.dp))
                        Text(stringResource(R.string.expense_edit_items_add_row_button))
                    }
                }
            }

            Spacer(Modifier.height(8.dp))
            ReconciliationFooter(drafts = drafts, parentAmountCents = parentAmountCents)
            Spacer(Modifier.height(12.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                OutlinedButton(
                    onClick = onDismiss,
                    enabled = !saving,
                    modifier = Modifier.weight(1f),
                ) { Text(stringResource(R.string.common_cancel)) }
                Button(
                    onClick = onSave,
                    enabled = !saving,
                    modifier = Modifier.weight(1f),
                ) {
                    Text(
                        if (saving) {
                            stringResource(R.string.expense_edit_items_saving_button)
                        } else {
                            stringResource(R.string.expense_edit_items_save_button)
                        }
                    )
                }
            }
            Spacer(Modifier.height(12.dp))
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
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            OutlinedTextField(
                value = draft.name,
                onValueChange = { onUpdate(index, it, null, null) },
                modifier = Modifier.weight(1f),
                singleLine = true,
                label = { Text(stringResource(R.string.expense_edit_items_row_name_label)) },
            )
            OutlinedTextField(
                value = draft.amountText,
                onValueChange = { onUpdate(index, null, it, null) },
                modifier = Modifier.width(112.dp),
                singleLine = true,
                label = { Text(stringResource(R.string.expense_edit_items_row_amount_label)) },
                prefix = { Text("¥") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            )
            IconButton(onClick = onRemove) {
                Icon(
                    Icons.Filled.Close,
                    contentDescription = stringResource(R.string.expense_edit_items_row_remove_desc),
                    tint = MaterialTheme.colorScheme.error,
                )
            }
        }
        Spacer(Modifier.height(6.dp))
        SingleChoiceSegmentedButtonRow(modifier = Modifier.fillMaxWidth()) {
            ITEM_KINDS.forEachIndexed { i, pair ->
                SegmentedButton(
                    selected = draft.kind == pair.first,
                    onClick = { onUpdate(index, null, null, pair.first) },
                    shape = SegmentedButtonDefaults.itemShape(index = i, count = ITEM_KINDS.size),
                ) { Text(stringResource(pair.second)) }
            }
        }
    }
}

@Composable
private fun ReconciliationFooter(
    drafts: List<EditableItem>,
    parentAmountCents: Long?,
) {
    val total = drafts.sumOf { draftSignedCents(it) }
    val diff = parentAmountCents?.let { total - it }
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text(stringResource(R.string.expense_edit_items_footer_total_label), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(formatDisplayAmount(total), style = MaterialTheme.typography.bodyMedium)
        }
        if (parentAmountCents != null) {
            Spacer(Modifier.height(4.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(stringResource(R.string.expense_edit_items_footer_face_label), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(formatDisplayAmount(parentAmountCents), style = MaterialTheme.typography.bodyMedium)
            }
        }
        if (diff != null && diff != 0L) {
            Spacer(Modifier.height(4.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text(stringResource(R.string.expense_edit_items_footer_diff_label), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.error)
                Text(
                    formatDisplayAmount(diff),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }
    }
}

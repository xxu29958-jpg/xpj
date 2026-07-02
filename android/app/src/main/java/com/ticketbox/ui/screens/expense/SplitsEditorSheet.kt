package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.EditableSplit

/**
 * ADR-0042 Slice E-1 splits editor. A full-height [ModalBottomSheet] mirroring
 * [ItemsEditorSheet]: each ledger member is a checklist row (included? + name +
 * an amount field in exact yuan) with a pinned reconciliation footer (分摊合计 /
 * 账单金额 / 差额). A 「均分」 button fills the checked members with a deterministic
 * largest-remainder split (see [evenSplitCents]); the user can still edit any
 * amount afterwards. Save is never blocked on a mismatch — the backend allows
 * non-summing splits, so the difference is surfaced as quiet status with a
 * non-blocking "点击均分可平账" hint, not an error.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SplitsEditorSheet(
    drafts: List<EditableSplit>,
    parentAmountCents: Long?,
    saving: Boolean,
    loading: Boolean,
    onToggleMember: (memberId: Long, included: Boolean) -> Unit,
    onUpdateAmount: (memberId: Long, amountText: String) -> Unit,
    onEvenSplit: () -> Unit,
    onSave: () -> Unit,
    onDismiss: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheetState) {
        ExpenseEditSheetScaffold(
            title = stringResource(R.string.expense_edit_splits_sheet_title),
            subtitle = stringResource(R.string.expense_edit_splits_sheet_subtitle),
        ) {
            if (drafts.isEmpty()) {
                // ADR-0042 P1: the roster loads async after the sheet opens. Until
                // drafts is built, Save is disabled (below) so an empty splits=[]
                // can't wipe the existing splits; show why the editor is inert.
                Text(
                    text = if (loading) {
                        stringResource(R.string.expense_edit_splits_members_loading)
                    } else {
                        stringResource(R.string.expense_edit_splits_members_failed)
                    },
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(vertical = AppSpacing.contentGap),
                )
            }

            LazyColumn(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = AppSpacing.controlMinHeight * 7),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            ) {
                items(drafts, key = { it.memberId }) { draft ->
                    SplitEditorRow(
                        draft = draft,
                        onToggle = { included -> onToggleMember(draft.memberId, included) },
                        onUpdateAmount = { text -> onUpdateAmount(draft.memberId, text) },
                    )
                }
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
            ) {
                AppSecondaryButton(
                    text = stringResource(R.string.expense_edit_splits_even_button),
                    enabled = !saving && drafts.isNotEmpty(),
                    onClick = onEvenSplit,
                )
            }
            SplitsReconciliationFooter(drafts = drafts, parentAmountCents = parentAmountCents)
            // ADR-0042 P1: never enable Save with an empty draft list — the roster
            // hasn't loaded, and saving would send splits=[] which the backend
            // replace turns into "delete all existing splits".
            ExpenseEditSheetActions(
                state = ExpenseEditSheetActionState(
                    saving = saving,
                    primaryEnabled = drafts.isNotEmpty(),
                    savingText = stringResource(R.string.expense_edit_splits_saving_button),
                    primaryText = stringResource(R.string.expense_edit_splits_save_button),
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
private fun SplitEditorRow(
    draft: EditableSplit,
    onToggle: (included: Boolean) -> Unit,
    onUpdateAmount: (amountText: String) -> Unit,
) {
    // A member already on a split but now disabled stays visible but read-only
    // so historical attribution isn't dropped (the user can't re-include or
    // edit a disabled member; the server keeps the existing row on replay).
    val editable = !draft.disabled
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Checkbox(
                checked = draft.included,
                onCheckedChange = if (editable) ({ onToggle(it) }) else null,
                enabled = editable,
            )
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = draft.displayName,
                    style = MaterialTheme.typography.bodyLarge,
                    color = if (editable) {
                        MaterialTheme.colorScheme.onSurface
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                )
                if (draft.disabled) {
                    Text(
                        text = stringResource(R.string.expense_edit_splits_member_disabled),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
        ExpenseEditTextField(
            state = ExpenseEditTextFieldState(
                label = stringResource(R.string.expense_edit_splits_row_amount_label),
                value = draft.amountText,
                placeholder = stringResource(R.string.components_amount_input_placeholder),
                enabled = editable && draft.included,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            ),
            onValueChange = onUpdateAmount,
        )
    }
}

@Composable
private fun SplitsReconciliationFooter(
    drafts: List<EditableSplit>,
    parentAmountCents: Long?,
) {
    val total = drafts.filter { it.included }.sumOf { parseAmountCents(it.amountText) ?: 0L }
    val diff = parentAmountCents?.let { total - it }
    ExpenseEditReconciliationRows(
        rows = listOfNotNull(
            ExpenseEditReconciliationLine(
                label = stringResource(R.string.expense_edit_splits_footer_total_label),
                value = formatDisplayAmount(total),
            ),
            parentAmountCents?.let {
                ExpenseEditReconciliationLine(
                    label = stringResource(R.string.expense_edit_splits_footer_bill_label),
                    value = formatDisplayAmount(it),
                )
            },
            diff?.takeIf { it != 0L }?.let {
                ExpenseEditReconciliationLine(
                    label = stringResource(R.string.expense_edit_splits_footer_diff_label),
                    value = formatDisplayAmount(it),
                    emphasis = true,
                    hint = stringResource(R.string.expense_edit_splits_footer_even_hint),
                )
            },
        ),
    )
}

/**
 * Largest-remainder even split of [totalCents] across [count] members, by
 * position. ``base = totalCents / count`` (floor) goes to everyone; the first
 * ``r = totalCents % count`` members each get one extra cent. Deterministic by
 * index (NOT random), so ¥100.00/3 → 33.34 / 33.33 / 33.33. Returns an empty
 * list for ``count <= 0`` and treats a negative total as zero (the editor never
 * feeds a negative parent amount).
 */
fun evenSplitCents(totalCents: Long, count: Int): List<Long> {
    if (count <= 0) return emptyList()
    val safeTotal = totalCents.coerceAtLeast(0L)
    val base = safeTotal / count
    val remainder = (safeTotal % count).toInt()
    return List(count) { index -> if (index < remainder) base + 1 else base }
}

/**
 * [evenSplitCents] of [parentCents] across [activeCount] active members AFTER
 * reserving [fixedDisabledCents] for disabled members already on the split (whose
 * shares the user can't edit). The active shares + the fixed disabled shares then
 * sum back to the parent total, so 均分 actually drives 差额 to zero. An
 * over-reserved fixed total (> parent) clamps the distributable amount to zero.
 */
fun evenSplitActiveCents(parentCents: Long, fixedDisabledCents: Long, activeCount: Int): List<Long> =
    evenSplitCents((parentCents - fixedDisabledCents).coerceAtLeast(0L), activeCount)

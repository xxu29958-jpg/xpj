package com.ticketbox.ui.screens.expense

import com.ticketbox.ui.screens.settings.SettingsEntryRowOptions
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.CallSplit
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.SheetValue
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.key
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import com.ticketbox.ui.screens.settings.SettingsEntryRow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.components.parseAmountCentsForDisplay
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.EditableSplit
import com.ticketbox.ui.components.AppSheetActionFeedbackState

data class SplitsEditorSheetState(
    val drafts: List<EditableSplit>,
    val parentAmountCents: Long?,
    val saving: Boolean,
    val loading: Boolean,
    // 票据的服务端 home 币种：footer 合计解析与保存侧同口径（零小数 home 不 ×100）。
    val display: CurrencyDisplay = CurrencyDisplay.Base,
    val feedback: AppSheetActionFeedbackState = AppSheetActionFeedbackState(),
    val primaryText: String? = null,
    val subtitle: String? = null,
)

data class SplitsEditorSheetActions(
    val onToggleMember: (memberId: Long, included: Boolean) -> Unit,
    val onUpdateAmount: (memberId: Long, amountText: String) -> Unit,
    val onEvenSplit: () -> Unit,
    val onSave: () -> Unit,
    val onDismiss: () -> Unit,
)

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
    state: SplitsEditorSheetState,
    actions: SplitsEditorSheetActions,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true,
        confirmValueChange = { target -> !state.saving || target != SheetValue.Hidden })
    ModalBottomSheet(onDismissRequest = { if (!state.saving) actions.onDismiss() }, sheetState = sheetState) {
        ExpenseEditSheetScaffold(
            title = stringResource(R.string.expense_edit_splits_sheet_title),
            subtitle = state.subtitle ?: stringResource(R.string.expense_edit_splits_sheet_subtitle),
            actions = {
                // ADR-0042 P1: never enable Save with an empty draft list — the roster
                // hasn't loaded, and saving would send splits=[] which the backend
                // replace turns into "delete all existing splits".
                ExpenseEditSheetActions(
                    state = ExpenseEditSheetActionState(
                        saving = state.saving,
                        primaryEnabled = state.drafts.isNotEmpty(),
                        savingText = stringResource(R.string.expense_edit_splits_saving_button),
                        primaryText = state.primaryText ?: stringResource(R.string.expense_edit_splits_save_button),
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
            if (state.drafts.isEmpty()) {
                // ADR-0042 P1: the roster loads async after the sheet opens. Until
                // drafts is built, Save is disabled (below) so an empty splits=[]
                // can't wipe the existing splits; show why the editor is inert.
                Text(
                    text = if (state.loading) {
                        stringResource(R.string.expense_edit_splits_members_loading)
                    } else {
                        stringResource(R.string.expense_edit_splits_members_failed)
                    },
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(vertical = AppSpacing.contentGap),
                )
            }

            Column(
                modifier = Modifier.fillMaxWidth(),
                verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap),
            ) {
                state.drafts.forEach { draft -> key(draft.memberId) {
                    SplitEditorRow(
                        draft = draft,
                        display = state.display,
                        enabled = !state.saving,
                        onToggle = { included -> actions.onToggleMember(draft.memberId, included) },
                        onUpdateAmount = { text -> actions.onUpdateAmount(draft.memberId, text) },
                    )
                } }
            }

            ExpenseDetailActionButtonRow(
                text = stringResource(R.string.expense_edit_splits_even_button),
                icon = Icons.AutoMirrored.Filled.CallSplit,
                enabled = !state.saving && state.drafts.isNotEmpty(),
                onClick = actions.onEvenSplit,
            )
            SplitsReconciliationFooter(
                drafts = state.drafts,
                parentAmountCents = state.parentAmountCents,
                display = state.display,
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SplitEditorRow(
    draft: EditableSplit,
    display: CurrencyDisplay,
    enabled: Boolean,
    onToggle: (included: Boolean) -> Unit,
    onUpdateAmount: (amountText: String) -> Unit,
) {
    val editable = !draft.disabled && enabled
    var expanded by rememberSaveable(draft.memberId) { mutableStateOf(false) }
    val status = stringResource(when {
        draft.disabled -> R.string.expense_edit_splits_member_disabled
        draft.included -> R.string.expense_edit_splits_member_included
        else -> R.string.expense_edit_splits_member_excluded
    })
    Column(modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
        SettingsEntryRow(
            title = draft.displayName,
            subtitle = listOfNotNull(status, draft.note?.takeIf { it.isNotBlank() }).joinToString(" · "),
            icon = R.drawable.ic_lucide_user_round,
            onClick = if (editable) ({ expanded = !expanded }) else null,
            options = SettingsEntryRowOptions(
                amount = if (draft.included) formatDisplayAmount(parseAmountCentsForDisplay(draft.amountText, display), display) else null,
                expanded = expanded, modifier = Modifier.testTag("expense-split-editor-${draft.memberId}"),
            ),
        )
        if (expanded && !draft.disabled) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Checkbox(checked = draft.included, onCheckedChange = onToggle, enabled = editable)
                Text(stringResource(R.string.expense_edit_splits_member_included), style = MaterialTheme.typography.bodyLarge)
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
                fieldModifier = Modifier.testTag("expense-split-amount-${draft.memberId}"),
            )
        }
    }
}

@Composable
private fun SplitsReconciliationFooter(
    drafts: List<EditableSplit>,
    parentAmountCents: Long?,
    display: CurrencyDisplay,
) {
    // 显示与保存/解析同源于票据 record 币种（JPY 零小数整数显示整数；未知码亮原码+原
    // minor，R14-1），不读恒 Base 的 LocalCurrencyDisplay（PR#255 P1）。R15b-2：未知码
    // 草稿金额按原 minor 整数解析（与回填/显示同空间，不按兜底枚举放大 100×）。
    val amounts = drafts.filter { it.included }.map { parseAmountCentsForDisplay(it.amountText, display) }
    val total = if (amounts.any { it == null }) null else amounts.filterNotNull().sum()
    val diff = parentAmountCents?.let { parent -> total?.minus(parent) }
    ExpenseEditReconciliationRows(
        rows = listOfNotNull(
            ExpenseEditReconciliationLine(
                label = stringResource(R.string.expense_edit_splits_footer_total_label),
                value = formatDisplayAmount(total, display),
            ),
            parentAmountCents?.let {
                ExpenseEditReconciliationLine(
                    label = stringResource(R.string.expense_edit_splits_footer_bill_label),
                    value = formatDisplayAmount(it, display),
                )
            },
            diff?.takeIf { it != 0L }?.let {
                ExpenseEditReconciliationLine(
                    label = stringResource(R.string.expense_edit_splits_footer_diff_label),
                    value = formatDisplayAmount(it, display),
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

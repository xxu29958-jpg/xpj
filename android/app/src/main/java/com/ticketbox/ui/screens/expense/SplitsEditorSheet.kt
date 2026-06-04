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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.Checkbox
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.components.parseAmountCents
import com.ticketbox.viewmodel.EditableSplit

/**
 * ADR-0042 Slice E-1 splits editor. A full-height [ModalBottomSheet] mirroring
 * [ItemsEditorSheet]: each ledger member is a checklist row (included? + name +
 * an amount field in exact yuan) with a pinned reconciliation footer (合计 / 票面
 * / 差额). A 「均分」 button fills the checked members with a deterministic
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
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .navigationBarsPadding(),
        ) {
            Text("编辑家庭拆账", style = MaterialTheme.typography.titleMedium)
            Spacer(Modifier.height(4.dp))
            Text(
                "勾选参与分摊的家庭成员并填写各自金额；拆账只记录分摊，不改动原始账单金额。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Spacer(Modifier.height(12.dp))

            if (drafts.isEmpty()) {
                // ADR-0042 P1: the roster loads async after the sheet opens. Until
                // drafts is built, Save is disabled (below) so an empty splits=[]
                // can't wipe the existing splits; show why the editor is inert.
                Text(
                    text = if (loading) "正在加载家庭成员…" else "家庭成员暂时加载失败，请关闭后重试。",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(vertical = 24.dp),
                )
            }

            LazyColumn(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(max = 380.dp),
                verticalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                items(drafts, key = { it.memberId }) { draft ->
                    SplitEditorRow(
                        draft = draft,
                        onToggle = { included -> onToggleMember(draft.memberId, included) },
                        onUpdateAmount = { text -> onUpdateAmount(draft.memberId, text) },
                    )
                }
            }

            Spacer(Modifier.height(8.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.End,
            ) {
                OutlinedButton(onClick = onEvenSplit, enabled = !saving && drafts.isNotEmpty()) { Text("均分") }
            }
            Spacer(Modifier.height(8.dp))
            SplitsReconciliationFooter(drafts = drafts, parentAmountCents = parentAmountCents)
            Spacer(Modifier.height(12.dp))

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
            ) {
                OutlinedButton(
                    onClick = onDismiss,
                    enabled = !saving,
                    modifier = Modifier.weight(1f),
                ) { Text("取消") }
                Button(
                    // ADR-0042 P1: never enable Save with an empty draft list — the
                    // roster hasn't loaded, and saving would send splits=[] which the
                    // backend replace turns into "delete all existing splits".
                    onClick = onSave,
                    enabled = !saving && drafts.isNotEmpty(),
                    modifier = Modifier.weight(1f),
                ) { Text(if (saving) "保存中…" else "保存") }
            }
            Spacer(Modifier.height(12.dp))
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
    Row(
        modifier = Modifier.fillMaxWidth(),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
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
                    text = "成员已停用",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
        }
        OutlinedTextField(
            value = draft.amountText,
            onValueChange = onUpdateAmount,
            modifier = Modifier.width(120.dp),
            singleLine = true,
            enabled = editable && draft.included,
            label = { Text("金额") },
            prefix = { Text("¥") },
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
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
    Column(modifier = Modifier.fillMaxWidth()) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
        ) {
            Text("合计", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            Text(formatDisplayAmount(total), style = MaterialTheme.typography.bodyMedium)
        }
        if (parentAmountCents != null) {
            Spacer(Modifier.height(4.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
            ) {
                Text("票面", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(formatDisplayAmount(parentAmountCents), style = MaterialTheme.typography.bodyMedium)
            }
        }
        if (diff != null && diff != 0L) {
            Spacer(Modifier.height(4.dp))
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column {
                    Text("差额", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.error)
                    Text(
                        "点击均分可平账",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
                Text(
                    formatDisplayAmount(diff),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error,
                )
            }
        }
    }
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

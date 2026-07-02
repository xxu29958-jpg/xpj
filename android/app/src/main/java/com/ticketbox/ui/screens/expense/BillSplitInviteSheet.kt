package com.ticketbox.ui.screens.expense

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.tabularNum

/**
 * UI/UX 第三波 批 13：跨账本拆账发起 sheet（ADR-0029）。从一笔已确认账单向**本账本
 * 成员**单选一位发起拆账邀请：成员单选（只展示 displayName，不露任何 id）+ 分摊金额
 * （exact yuan）。**在线-only**：发送失败的错误直接在 sheet 内展示（[BillSplitInviteSheetState.message]），
 * 不入离线队列、不假装已发——该面无幂等键。镜像 [SplitsEditorSheet] 的 ModalBottomSheet 结构。
 */
@Immutable
internal data class BillSplitInviteSheetState(
    val members: List<FamilyMember>,
    val membersLoading: Boolean,
    val selectedMemberId: Long?,
    val amountText: String,
    val sending: Boolean,
    val message: UiText?,
)

internal data class BillSplitInviteSheetActions(
    val onSelectMember: (memberId: Long) -> Unit,
    val onUpdateAmount: (amountText: String) -> Unit,
    val onSend: () -> Unit,
    val onDismiss: () -> Unit,
)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun BillSplitInviteSheet(
    state: BillSplitInviteSheetState,
    remainingCents: Long?,
    actions: BillSplitInviteSheetActions,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = actions.onDismiss, sheetState = sheetState) {
        ExpenseEditSheetScaffold(
            title = stringResource(R.string.expense_edit_bill_split_sheet_title),
            subtitle = stringResource(R.string.expense_edit_bill_split_sheet_subtitle),
        ) {
            BillSplitInviteMemberLabel()
            BillSplitInviteMemberList(
                members = state.members,
                membersLoading = state.membersLoading,
                selectedMemberId = state.selectedMemberId,
                onSelect = actions.onSelectMember,
            )
            BillSplitInviteAmountField(
                amountText = state.amountText,
                remainingCents = remainingCents,
                sending = state.sending,
                onUpdateAmount = actions.onUpdateAmount,
            )
            state.message?.let {
                Text(
                    it.asString(),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
            ExpenseEditSheetActions(
                state = ExpenseEditSheetActionState(
                    saving = state.sending,
                    primaryEnabled = state.selectedMemberId != null && state.members.isNotEmpty(),
                    savingText = stringResource(R.string.expense_edit_bill_split_sheet_sending_button),
                    primaryText = stringResource(R.string.expense_edit_bill_split_sheet_send_button),
                ),
                handlers = ExpenseEditSheetActionHandlers(
                    onDismiss = actions.onDismiss,
                    onSubmit = actions.onSend,
                ),
            )
        }
    }
}

@Composable
private fun BillSplitInviteMemberLabel() {
    Text(
        stringResource(R.string.expense_edit_bill_split_sheet_member_label),
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun BillSplitInviteAmountField(
    amountText: String,
    remainingCents: Long?,
    sending: Boolean,
    onUpdateAmount: (String) -> Unit,
) {
    ExpenseEditTextField(
        state = ExpenseEditTextFieldState(
            label = stringResource(R.string.expense_edit_bill_split_sheet_amount_label),
            value = amountText,
            placeholder = stringResource(R.string.components_amount_input_placeholder),
            enabled = !sending,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        ),
        onValueChange = onUpdateAmount,
    )
    remainingCents?.let {
        Text(
            stringResource(R.string.expense_edit_bill_split_sheet_remaining, formatDisplayAmount(it)),
            style = MaterialTheme.typography.bodySmall.tabularNum(),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun BillSplitInviteMemberList(
    members: List<FamilyMember>,
    membersLoading: Boolean,
    selectedMemberId: Long?,
    onSelect: (memberId: Long) -> Unit,
) {
    if (members.isEmpty()) {
        Text(
            text = if (membersLoading) {
                stringResource(R.string.expense_edit_splits_members_loading)
            } else {
                stringResource(R.string.expense_edit_bill_split_sheet_no_members)
            },
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(vertical = AppSpacing.contentGap),
        )
        return
    }
    LazyColumn(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(max = AppSpacing.controlMinHeight * 5),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.tinyGap),
    ) {
        items(members, key = { it.memberId }) { member ->
            BillSplitInviteMemberRow(
                member = member,
                selected = member.memberId == selectedMemberId,
                onSelect = { onSelect(member.memberId) },
            )
        }
    }
}

@Composable
private fun BillSplitInviteMemberRow(
    member: FamilyMember,
    selected: Boolean,
    onSelect: () -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .selectable(selected = selected, onClick = onSelect)
            .padding(vertical = AppSpacing.smallGap),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        RadioButton(selected = selected, onClick = onSelect)
        Text(
            text = member.displayName,
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
}

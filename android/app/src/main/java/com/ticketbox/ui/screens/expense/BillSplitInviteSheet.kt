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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.Immutable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.formatDisplayAmount

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
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 20.dp)
                .navigationBarsPadding(),
        ) {
            BillSplitInviteHeader()
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
                Spacer(Modifier.height(8.dp))
                Text(
                    it.asString(),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error,
                )
            }
            Spacer(Modifier.height(16.dp))
            BillSplitInviteActionsRow(state = state, actions = actions)
            Spacer(Modifier.height(12.dp))
        }
    }
}

@Composable
private fun BillSplitInviteHeader() {
    Text(stringResource(R.string.expense_edit_bill_split_sheet_title), style = MaterialTheme.typography.titleMedium)
    Spacer(Modifier.height(4.dp))
    Text(
        stringResource(R.string.expense_edit_bill_split_sheet_subtitle),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
    Spacer(Modifier.height(12.dp))
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
    Spacer(Modifier.height(12.dp))
    OutlinedTextField(
        value = amountText,
        onValueChange = onUpdateAmount,
        modifier = Modifier.fillMaxWidth(),
        singleLine = true,
        enabled = !sending,
        label = { Text(stringResource(R.string.expense_edit_bill_split_sheet_amount_label)) },
        prefix = { Text("¥") },
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
    )
    remainingCents?.let {
        Spacer(Modifier.height(4.dp))
        Text(
            stringResource(R.string.expense_edit_bill_split_sheet_remaining, formatDisplayAmount(it)),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun BillSplitInviteActionsRow(
    state: BillSplitInviteSheetState,
    actions: BillSplitInviteSheetActions,
) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        OutlinedButton(
            onClick = actions.onDismiss,
            enabled = !state.sending,
            modifier = Modifier.weight(1f),
        ) { Text(stringResource(R.string.common_cancel)) }
        Button(
            onClick = actions.onSend,
            enabled = !state.sending && state.selectedMemberId != null && state.members.isNotEmpty(),
            modifier = Modifier.weight(1f),
        ) {
            Text(
                if (state.sending) {
                    stringResource(R.string.expense_edit_bill_split_sheet_sending_button)
                } else {
                    stringResource(R.string.expense_edit_bill_split_sheet_send_button)
                }
            )
        }
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
            modifier = Modifier.padding(vertical = 16.dp),
        )
        return
    }
    LazyColumn(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(max = 280.dp),
        verticalArrangement = Arrangement.spacedBy(4.dp),
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
            .padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        RadioButton(selected = selected, onClick = onSelect)
        Text(
            text = member.displayName,
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
}

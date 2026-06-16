package com.ticketbox.ui.screens

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.MemberRepaymentProposal
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.components.rememberAppHaptics
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.viewmodel.MemberProposalUiState
import com.ticketbox.viewmodel.MemberRepaymentProposalViewModel
import com.ticketbox.viewmodel.ProposalForm

/**
 * ADR-0049 §3.2 (slice 8d) 成员欠款 repayment proposal 收发箱 —— [DebtDetailScreen] 对**成员**欠款渲染的
 * 动作面板（替换 slice8c 留的「走对方确认流程」占位提示）。角色由**服务端权威字段** [Debt.viewerIsDebtor]
 * 给出（客户端不推导——详见 [Debt] 的 KDoc）：债务人发起「我已还款」/ 撤回，
 * 债权人确认（全额/部分）/ 拒绝。已结清/作废/只读各显示对应说明。**在途 pending** 由债务人/债权人卡承载，
 * **已解决** proposal 沉降到 [ResolvedHistoryCard]「过往」(8e ③，§3.2 pending 不进历史避免一件事出现两次)。
 * 这些 composable 独立成文件而非堆进 DebtDetailScreen.kt，避免顶破后者的文件级 TooManyFunctions 门
 * （[[project_android_compose_detekt_limits]]）。复用 DebtDetailScreen 的 internal [DebtNoteCard] /
 * [DebtActionFormButtons] 与 DebtGoalLabels 的 [DebtStatusBadge]。
 */
@Composable
internal fun MemberProposalSection(
    debt: Debt,
    state: MemberProposalUiState,
    viewModel: MemberRepaymentProposalViewModel,
    currency: CurrencyDisplay,
) {
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap)) {
        when {
            debt.isVoided -> DebtNoteCard(stringResource(R.string.debt_proposal_voided_note))
            debt.isCleared -> DebtNoteCard(stringResource(R.string.debt_proposal_cleared_note))
            !state.canModify -> DebtNoteCard(stringResource(R.string.debt_proposal_readonly_note))
            // Role is the server-authoritative Debt.viewerIsDebtor (§3.2); null = the viewer is not a
            // party to this member Debt (a third ledger member), so neither action card applies.
            debt.viewerIsDebtor == true -> DebtorProposalCard(state = state, viewModel = viewModel)
            debt.viewerIsDebtor == false -> CreditorProposalCard(debt = debt, state = state, viewModel = viewModel, currency = currency)
            else -> DebtNoteCard(stringResource(R.string.debt_proposal_not_party_note))
        }
        // ③ 沉降：只已解决进历史 (空集时整卡不渲染，§3.2/3.6)；在途 pending 在上面的动作卡里。
        val resolved = state.proposals.filter { !it.isPending }
        if (resolved.isNotEmpty()) {
            ResolvedHistoryCard(resolved = resolved, currency = currency)
        }
    }
}

@Composable
private fun DebtorProposalCard(state: MemberProposalUiState, viewModel: MemberRepaymentProposalViewModel) {
    val pending = state.pendingProposal
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Text(
                stringResource(R.string.debt_proposal_debtor_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            if (pending != null) {
                Text(
                    stringResource(R.string.debt_proposal_debtor_pending_hint),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                OutlinedButton(
                    onClick = { viewModel.withdraw(pending.publicId) },
                    enabled = !state.isSubmitting,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text(stringResource(R.string.debt_proposal_withdraw_action)) }
            } else {
                // §1.4 post-reject：对方回了「金额对不上」且当前无在途 → neutral 提示 + 复用下方重发入口
                // （描述对方动作 + 邀请重试，不指责债务人，绝不 danger）。
                if (state.showDebtorAfterReject) {
                    Text(
                        stringResource(R.string.debt_proposal_debtor_after_reject),
                        style = MaterialTheme.typography.bodyMedium,
                        color = LocalStateTokens.current.neutral.fg,
                    )
                }
                Text(
                    stringResource(R.string.debt_proposal_debtor_hint),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                Button(
                    onClick = { viewModel.openForm(ProposalForm.Propose) },
                    enabled = !state.isSubmitting,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text(stringResource(R.string.debt_proposal_propose_action)) }
            }
        }
    }
}

@Composable
private fun CreditorProposalCard(
    debt: Debt,
    state: MemberProposalUiState,
    viewModel: MemberRepaymentProposalViewModel,
    currency: CurrencyDisplay,
) {
    val pending = state.pendingProposal
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Text(
                stringResource(R.string.debt_proposal_creditor_title),
                style = MaterialTheme.typography.titleMedium,
                fontWeight = FontWeight.SemiBold,
            )
            if (pending == null) {
                Text(
                    stringResource(R.string.debt_proposal_creditor_waiting),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                // 8e ④ forgive：仅债权人 + open 成员债 + 无在途 proposal（pending==null）时显示，低调
                // TextButton，不与「确认收款」抢主操作（pending 时只给确认/拒绝，避免与债务人在途请求并存）。
                CreditorForgiveAction(debt = debt, isSubmitting = state.isSubmitting, viewModel = viewModel)
            } else {
                Text(
                    stringResource(
                        R.string.debt_proposal_creditor_pending,
                        formatDisplayAmount(pending.proposedAmountCents, currency),
                    ),
                    style = MaterialTheme.typography.bodyMedium,
                )
                pending.note?.takeIf { it.isNotBlank() }?.let { note ->
                    Text(note, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                CreditorActionButtons(pending = pending, isSubmitting = state.isSubmitting, viewModel = viewModel)
            }
        }
    }
}

@Composable
private fun CreditorActionButtons(
    pending: MemberRepaymentProposal,
    isSubmitting: Boolean,
    viewModel: MemberRepaymentProposalViewModel,
) {
    Row(modifier = Modifier.fillMaxWidth()) {
        Button(
            onClick = { viewModel.openForm(ProposalForm.Confirm, pending) },
            enabled = !isSubmitting,
            modifier = Modifier.weight(1f),
        ) { Text(stringResource(R.string.debt_proposal_confirm_action)) }
        Spacer(Modifier.width(AppSpacing.smallGap))
        OutlinedButton(
            onClick = { viewModel.reject(pending.publicId) },
            enabled = !isSubmitting,
            modifier = Modifier.weight(1f),
        ) { Text(stringResource(R.string.debt_proposal_reject_action)) }
    }
}

// 8e ④ forgive 入口 + 二次确认弹窗（communal 应需而免 + haptic.confirm() 配单向赠与的软触感）。债权人确认后
// viewModel.forgive 把欠款折成 cleared(forgiven)，详情屏重拉到 is_forgiven 暖语；OCC 冲突走 neutral 提示。
@Composable
private fun CreditorForgiveAction(
    debt: Debt,
    isSubmitting: Boolean,
    viewModel: MemberRepaymentProposalViewModel,
) {
    var showConfirm by rememberSaveable { mutableStateOf(false) }
    val haptic = rememberAppHaptics()
    TextButton(
        onClick = { showConfirm = true },
        enabled = !isSubmitting,
        modifier = Modifier.fillMaxWidth(),
    ) { Text(stringResource(R.string.debt_member_forgive_action)) }
    if (showConfirm) {
        AlertDialog(
            onDismissRequest = { showConfirm = false },
            title = { Text(stringResource(R.string.debt_member_forgive_confirm_title)) },
            text = { Text(stringResource(R.string.debt_member_forgive_confirm_body)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        showConfirm = false
                        haptic.confirm()
                        viewModel.forgive(debt.rowVersion)
                    },
                ) { Text(stringResource(R.string.debt_member_forgive_confirm_action)) }
            },
            dismissButton = {
                TextButton(onClick = { showConfirm = false }) {
                    Text(stringResource(R.string.common_cancel))
                }
            },
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun ProposalFormSheet(
    state: MemberProposalUiState,
    viewModel: MemberRepaymentProposalViewModel,
    expectedRowVersion: Long,
    onClose: () -> Unit,
) {
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = onClose, sheetState = sheetState) {
        ProposalForm(
            state = state,
            viewModel = viewModel,
            onSubmit = { viewModel.submit(expectedRowVersion) },
            onCancel = onClose,
        )
    }
}

@Composable
private fun ProposalForm(
    state: MemberProposalUiState,
    viewModel: MemberRepaymentProposalViewModel,
    onSubmit: () -> Unit,
    onCancel: () -> Unit,
) {
    val form = state.activeForm ?: return
    Column(modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding)) {
        Text(
            stringResource(proposalFormTitleRes(form)),
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.SemiBold,
        )
        Spacer(Modifier.size(AppSpacing.cardPadding))
        OutlinedTextField(
            value = state.amountInput,
            onValueChange = viewModel::updateAmount,
            label = { Text(stringResource(R.string.debt_action_amount_label)) },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            modifier = Modifier.fillMaxWidth(),
        )
        if (form == ProposalForm.Propose) {
            Spacer(Modifier.size(AppSpacing.compactGap))
            OutlinedTextField(
                value = state.noteInput,
                onValueChange = viewModel::updateNote,
                label = { Text(stringResource(R.string.debt_proposal_note_label)) },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
        }
        state.validationError?.let { err ->
            Spacer(Modifier.size(AppSpacing.smallGap))
            Text(err.asString(), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
        }
        Spacer(Modifier.size(AppSpacing.cardPadding))
        HorizontalDivider()
        Spacer(Modifier.size(AppSpacing.compactGap))
        DebtActionFormButtons(isSubmitting = state.isSubmitting, onSubmit = onSubmit, onCancel = onCancel)
        Spacer(Modifier.size(AppSpacing.compactGap))
    }
}

@StringRes
private fun proposalFormTitleRes(form: ProposalForm): Int = when (form) {
    ProposalForm.Propose -> R.string.debt_proposal_propose_title
    ProposalForm.Confirm -> R.string.debt_proposal_confirm_title
}

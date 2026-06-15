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
import androidx.compose.material3.Button
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.MemberProposalStatuses
import com.ticketbox.domain.model.MemberRepaymentProposal
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppGlassCard
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.ui.design.StateTone
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.MemberProposalUiState
import com.ticketbox.viewmodel.MemberRepaymentProposalViewModel
import com.ticketbox.viewmodel.ProposalForm

/**
 * ADR-0049 §3.2 (slice 8d) 成员欠款 repayment proposal 收发箱 —— [DebtDetailScreen] 对**成员**欠款渲染的
 * 动作面板（替换 slice8c 留的「走对方确认流程」占位提示）。角色由 [Debt.viewerIsDebtor] 推导
 * （[Debt] 的 KDoc 解释为何用 `ledgerId`+`direction` 而非 account_id）：债务人发起「我已还款」/ 撤回，
 * 债权人确认（全额/部分）/ 拒绝。已结清/作废/只读各显示对应说明；下方始终显示 proposal 历史（如有）。
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
            debt.viewerIsDebtor == false -> CreditorProposalCard(state = state, viewModel = viewModel, currency = currency)
            else -> DebtNoteCard(stringResource(R.string.debt_proposal_not_party_note))
        }
        if (state.proposals.isNotEmpty()) {
            ProposalHistoryCard(proposals = state.proposals, currency = currency)
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

@Composable
private fun ProposalHistoryCard(proposals: List<MemberRepaymentProposal>, currency: CurrencyDisplay) {
    AppGlassCard(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
            verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
        ) {
            Text(
                stringResource(R.string.debt_proposal_history_title),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            proposals.forEach { proposal -> ProposalHistoryRow(proposal = proposal, currency = currency) }
        }
    }
}

@Composable
private fun ProposalHistoryRow(proposal: MemberRepaymentProposal, currency: CurrencyDisplay) {
    Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                formatDisplayAmount(proposal.proposedAmountCents, currency),
                style = MaterialTheme.typography.bodyMedium.tabularNum(),
                fontWeight = FontWeight.Medium,
            )
            proposal.note?.takeIf { it.isNotBlank() }?.let { note ->
                Text(note, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        DebtStatusBadge(
            text = stringResource(memberProposalStatusLabelRes(proposal.status)),
            tone = memberProposalStatusTone(proposal.status),
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

/** ADR-0049 §3.2 (slice 8d): member repayment-proposal status → localized label. */
@StringRes
private fun memberProposalStatusLabelRes(status: String): Int = when (status) {
    MemberProposalStatuses.PENDING -> R.string.debt_proposal_status_pending
    MemberProposalStatuses.CONFIRMED -> R.string.debt_proposal_status_confirmed
    MemberProposalStatuses.PARTIALLY_CONFIRMED -> R.string.debt_proposal_status_partially_confirmed
    MemberProposalStatuses.REJECTED -> R.string.debt_proposal_status_rejected
    MemberProposalStatuses.WITHDRAWN -> R.string.debt_proposal_status_withdrawn
    MemberProposalStatuses.EXPIRED -> R.string.debt_proposal_status_expired
    MemberProposalStatuses.SUPERSEDED -> R.string.debt_proposal_status_superseded
    else -> R.string.debt_proposal_status_pending
}

@Composable
private fun memberProposalStatusTone(status: String): StateTone {
    val tokens = LocalStateTokens.current
    return when (status) {
        MemberProposalStatuses.CONFIRMED, MemberProposalStatuses.PARTIALLY_CONFIRMED -> tokens.success
        MemberProposalStatuses.PENDING -> tokens.info
        else -> tokens.neutral
    }
}

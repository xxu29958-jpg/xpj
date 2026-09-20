package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppSectionGroup
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.QuietOutlinedButton
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.viewmodel.SplitAgreementUiState
import com.ticketbox.viewmodel.SplitAgreementViewModel

@Composable
internal fun SplitAgreementSection(
    state: SplitAgreementUiState,
    model: SplitAgreementViewModel,
    onOpenDebt: (String) -> Unit,
) {
    AppSectionGroup {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
            Text(stringResource(R.string.split_agreement_title), style = MaterialTheme.typography.titleMedium)
            state.error?.let { Text(it.asString(), color = MaterialTheme.colorScheme.error) }
            state.message?.let { Text(it.asString()) }
            if (state.loading) Text(stringResource(R.string.split_agreement_loading))
            QuietOutlinedButton(text = stringResource(R.string.split_agreement_refresh),
                onClick = model::refresh, enabled = !state.loading)
            state.agreement?.let { agreement ->
                val display = CurrencyDisplay.forRecord(agreement.homeCurrencyCode)
                SplitAgreementFacts(state, display, onOpenDebt)
                if (agreement.viewerIsParty) {
                    SplitAgreementProposal(state, model, display)
                }
            }
            SplitAgreementSubmissions(state, model)
        }
    }
}

@Composable
private fun SplitAgreementForm(state: SplitAgreementUiState, model: SplitAgreementViewModel, display: CurrencyDisplay) {
    val agreement = state.agreement ?: return
    AppTextInput(AppTextInputState(stringResource(R.string.split_agreement_share_input, agreement.homeCurrencyCode),
        state.shareInput, enabled = !state.busy),
        AppTextInputActions(onValueChange = { model.editDraft(share = it) }))
    QuietOutlinedButton(text = stringResource(R.string.split_agreement_preview),
        onClick = model::refresh, enabled = !state.busy && !state.loading)
    if (state.previewReady) {
        if (agreement.preview.requiresExplicitSettlement) {
            Text(stringResource(R.string.split_agreement_explicit_settlement_warning))
        }
        agreement.preview.cashBasedSettlementNetAmountCents?.let {
            Text(stringResource(R.string.split_agreement_cash_reference, splitSettlementLabel(it, display)))
        }
        AppTextInput(AppTextInputState(stringResource(R.string.split_agreement_settlement_input), state.settlementInput,
            enabled = !state.busy), AppTextInputActions(onValueChange = { model.editDraft(settlement = it) }))
        AppTextInput(AppTextInputState(stringResource(R.string.split_agreement_reason_input), state.reason,
            enabled = !state.busy, singleLine = false),
            AppTextInputActions(onValueChange = { model.editDraft(reason = it) }))
        SplitSettlementConfirmation(state, model)
        QuietOutlinedButton(text = stringResource(if (state.replacingProposalPublicId == null) {
            R.string.split_agreement_propose
        } else {
            R.string.split_agreement_submit_replacement
        }),
            onClick = model::propose, enabled = state.canPropose)
    }
}

@Composable
private fun SplitSettlementConfirmation(state: SplitAgreementUiState, model: SplitAgreementViewModel) {
    Row {
        Checkbox(checked = state.confirmed, onCheckedChange = model::confirm, enabled = !state.busy && !state.loading)
        Text(stringResource(R.string.split_agreement_confirmation))
    }
}

@Composable
internal fun splitSettlementLabel(amount: Long, display: CurrencyDisplay): String = when {
    amount > 0 -> stringResource(R.string.split_agreement_settlement_receiver_pays,
        formatDisplayAmount(amount, display))
    amount < 0 -> stringResource(R.string.split_agreement_settlement_sender_returns,
        formatDisplayAmount(-amount, display))
    else -> stringResource(R.string.split_agreement_settlement_clear)
}

@Composable
private fun SplitAgreementFacts(state: SplitAgreementUiState, display: CurrencyDisplay, onOpenDebt: (String) -> Unit) {
    val agreement = state.agreement ?: return
    Text(stringResource(R.string.split_agreement_share_facts,
        formatDisplayAmount(agreement.originalShareAmountCents, display),
        formatDisplayAmount(agreement.agreedShareAmountCents, display)))
    Text(stringResource(R.string.split_agreement_payment_facts,
        formatDisplayAmount(agreement.originalPaidAmountCents, display),
        formatDisplayAmount(agreement.returnPaidAmountCents, display)))
    Text(stringResource(R.string.split_agreement_forgiveness_facts,
        formatDisplayAmount(agreement.originalForgivenAmountCents, display),
        formatDisplayAmount(agreement.returnForgivenAmountCents, display)))
    Text(stringResource(R.string.split_agreement_current_settlement,
        splitSettlementLabel(agreement.settlementNetAmountCents, display)))
    Text(stringResource(R.string.split_agreement_private_records_notice))
    if (agreement.originalDebt.publicId != state.task?.debtPublicId) {
        QuietOutlinedButton(text = stringResource(R.string.split_agreement_open_original_debt),
            onClick = { onOpenDebt(agreement.originalDebt.publicId) })
    }
    agreement.returnDebt?.takeIf { it.publicId != state.task?.debtPublicId }?.let { debt ->
        QuietOutlinedButton(text = stringResource(R.string.split_agreement_open_return_debt),
            onClick = { onOpenDebt(debt.publicId) })
    }
    if (agreement.pendingRepaymentDebtPublicIds.isNotEmpty()) {
        Text(stringResource(R.string.split_agreement_pending_repayments))
        agreement.pendingRepaymentDebtPublicIds.forEach { id ->
            if (id == state.task?.debtPublicId) Text(stringResource(R.string.split_agreement_current_debt_pending))
            else QuietOutlinedButton(text = stringResource(R.string.split_agreement_process_declaration,
                stringResource(if (id == agreement.originalDebt.publicId) {
                    R.string.split_agreement_original_debt
                } else {
                    R.string.split_agreement_return_debt
                })),
                onClick = { onOpenDebt(id) })
        }
    }
}

@Composable
private fun SplitAgreementProposal(state: SplitAgreementUiState, model: SplitAgreementViewModel, display: CurrencyDisplay) {
    val agreement = state.agreement ?: return
    agreement.pendingProposal?.let { proposal ->
        Text(stringResource(R.string.split_agreement_proposal_summary,
            stringResource(if (proposal.proposedByYou) R.string.split_agreement_proposer_you
                else R.string.split_agreement_proposer_other),
            formatDisplayAmount(proposal.newShareAmountCents, display)))
        Text(stringResource(R.string.split_agreement_proposal_settlement,
            splitSettlementLabel(proposal.settlementNetAmountCents, display)))
        Text(proposal.reason)
        if (state.replacingProposalPublicId == proposal.publicId) {
            Text(stringResource(R.string.split_agreement_replacement_notice))
            SplitAgreementForm(state, model, display)
            QuietOutlinedButton(text = stringResource(R.string.split_agreement_cancel_replacement),
                onClick = model::cancelReplacement, enabled = !state.busy)
        } else {
            if (!proposal.proposedByYou) {
                SplitSettlementConfirmation(state, model)
                QuietOutlinedButton(text = stringResource(R.string.split_agreement_accept),
                    onClick = { model.resolve(true) },
                    enabled = state.commandsEnabled && state.previewReady && state.confirmed &&
                        agreement.pendingRepaymentDebtPublicIds.isEmpty())
            }
            QuietOutlinedButton(text = stringResource(if (proposal.proposedByYou) {
                R.string.split_agreement_withdraw
            } else {
                R.string.split_agreement_reject
            }),
                onClick = { model.resolve(false) }, enabled = state.commandsEnabled)
            QuietOutlinedButton(text = stringResource(R.string.split_agreement_replace),
                onClick = model::beginReplacement, enabled = state.commandsEnabled && agreement.viewerIsParty)
        }
    } ?: SplitAgreementForm(state, model, display)
}

@Composable
private fun SplitAgreementSubmissions(state: SplitAgreementUiState, model: SplitAgreementViewModel) {
    state.rows.filter { it.status != PendingMutationStatus.Done }.forEach { row ->
        state.intents[row.id]?.create?.let { submitted ->
            Text(stringResource(R.string.split_agreement_submitted_reason, submitted.reason))
            state.agreement?.homeCurrencyCode?.let { currency ->
                val display = CurrencyDisplay.forRecord(currency)
                Text(stringResource(R.string.split_agreement_submitted_share,
                    formatDisplayAmount(submitted.newShareAmountCents, display),
                    splitSettlementLabel(submitted.settlementNetAmountCents, display)))
            }
        }
        if (row.lastError in com.ticketbox.data.repository.SPLIT_SHARE_REFUSALS) {
            Text(stringResource(R.string.split_agreement_share_refused))
        }
        Text(stringResource(when (row.status) {
            PendingMutationStatus.Conflict -> R.string.split_agreement_submission_conflict
            PendingMutationStatus.Failed -> R.string.split_agreement_submission_failed
            else -> R.string.split_agreement_submission_waiting
        }))
        if (row.status == PendingMutationStatus.Failed && row.lastError !in com.ticketbox.data.repository.SPLIT_SHARE_REFUSALS) {
            QuietOutlinedButton(text = stringResource(R.string.split_agreement_retry_submission),
                onClick = { model.recover(row, false) })
        }
        if (row.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict)) {
            QuietOutlinedButton(text = stringResource(R.string.split_agreement_end_submission),
                onClick = { model.recover(row, true) })
        }
    }
}

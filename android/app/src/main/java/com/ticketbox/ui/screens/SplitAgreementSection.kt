package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Checkbox
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSectionGroup
import com.ticketbox.ui.components.AppTextInput
import com.ticketbox.ui.components.AppTextInputActions
import com.ticketbox.ui.components.AppTextInputState
import com.ticketbox.ui.components.AppSecondaryButton
import com.ticketbox.ui.components.formatDisplayAmount
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.tabularNum
import com.ticketbox.viewmodel.SplitAgreementUiState
import com.ticketbox.viewmodel.SplitAgreementViewModel

@Composable
internal fun SplitAgreementSection(
    state: SplitAgreementUiState,
    model: SplitAgreementViewModel,
    onOpenDebt: (String) -> Unit,
) {
    AppSectionGroup {
        Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            Text(stringResource(R.string.split_agreement_title), modifier = Modifier.weight(1f),
                style = MaterialTheme.typography.titleMedium)
            TextButton(onClick = model::refresh, enabled = !state.loading) {
                Text(stringResource(R.string.split_agreement_refresh))
            }
        }
        state.error?.let { Text(it.asString(), color = MaterialTheme.colorScheme.error) }
        if (state.loading) Text(stringResource(R.string.split_agreement_loading))
        DebtReadSource(state.fetchedAt, state.fromCache, state.loading, testTag = "split-agreement-read-source")
        state.agreement?.let { agreement ->
            SplitAgreementFacts(state, CurrencyDisplay.forRecord(agreement.homeCurrencyCode), onOpenDebt)
        }
        state.message?.let {
            Text(it.asString(), style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        SplitAgreementSubmissions(state, model)
        SplitAgreementDiscussion(state, model)
    }
}

@Composable
private fun SplitAgreementDiscussion(state: SplitAgreementUiState, model: SplitAgreementViewModel) {
    val agreement = state.agreement
    if (agreement?.viewerIsParty != true && !(agreement == null && state.hasDraft)) return
    var editorRequested by remember(state.task) { mutableStateOf(false) }
    if (!editorRequested && !state.hasDraft && agreement?.pendingProposal == null) {
        AppSecondaryButton(text = stringResource(R.string.split_agreement_discussion_title),
            onClick = { editorRequested = true }, enabled = state.canModify && !state.busy)
        return
    }
    Column(modifier = Modifier.padding(top = AppSpacing.cardGap),
        verticalArrangement = Arrangement.spacedBy(AppSpacing.compactGap)) {
        Text(stringResource(R.string.split_agreement_discussion_title), style = MaterialTheme.typography.titleMedium)
        val display = CurrencyDisplay.forRecord(agreement?.homeCurrencyCode ?: state.draftCurrencyCode ?: "UNKNOWN")
        if (agreement != null) {
            SplitAgreementProposal(state, model, display)
        } else {
            Text(stringResource(R.string.split_agreement_retained_draft))
            SplitAgreementForm(state, model, display)
        }
    }
}

@Composable
private fun SplitAgreementForm(state: SplitAgreementUiState, model: SplitAgreementViewModel, display: CurrencyDisplay) {
    val agreement = state.agreement
    val currency = state.draftCurrencyCode ?: agreement?.homeCurrencyCode ?: return
    AppTextInput(AppTextInputState(stringResource(R.string.split_agreement_share_input, currency),
        state.shareInput, enabled = state.canModify && !state.busy),
        AppTextInputActions(onValueChange = { model.editDraft(share = it) }))
    AppSecondaryButton(text = stringResource(R.string.split_agreement_preview),
        onClick = model::refresh, enabled = !state.busy && !state.loading)
    if (state.previewReady || state.hasDraft) {
        if (state.previewReady && agreement?.preview?.requiresExplicitSettlement == true) {
            Text(stringResource(R.string.split_agreement_explicit_settlement_warning))
        }
        agreement?.preview?.cashBasedSettlementNetAmountCents?.takeIf { state.previewReady }?.let {
            Text(stringResource(R.string.split_agreement_cash_reference, splitSettlementLabel(it, display)))
        }
        AppTextInput(AppTextInputState(stringResource(R.string.split_agreement_settlement_input), state.settlementInput,
            enabled = state.canModify && !state.busy), AppTextInputActions(onValueChange = { model.editDraft(settlement = it) }))
        AppTextInput(AppTextInputState(stringResource(R.string.split_agreement_reason_input), state.reason,
            enabled = state.canModify && !state.busy, singleLine = false),
            AppTextInputActions(onValueChange = { model.editDraft(reason = it) }))
        SplitSettlementConfirmation(state, model)
        AppPrimaryButton(text = stringResource(if (state.replacingProposalPublicId == null) {
            R.string.split_agreement_propose
        } else {
            R.string.split_agreement_submit_replacement
        }),
            icon = Icons.Filled.Check, modifier = Modifier.fillMaxWidth(),
            onClick = model::propose, enabled = state.canPropose)
    }
}

@Composable
private fun SplitSettlementConfirmation(state: SplitAgreementUiState, model: SplitAgreementViewModel) {
    Row {
        Checkbox(checked = state.confirmed, onCheckedChange = model::confirm,
            enabled = state.canModify && state.previewReady && !state.busy && !state.loading)
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
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Text(stringResource(R.string.split_agreement_current_settlement),
            style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(splitSettlementLabel(agreement.settlementNetAmountCents, display),
            style = MaterialTheme.typography.titleLarge.tabularNum())
    }
    Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.miniGap)) {
        Text(stringResource(R.string.split_agreement_share_facts,
            formatDisplayAmount(agreement.originalShareAmountCents, display),
            formatDisplayAmount(agreement.agreedShareAmountCents, display)),
            style = MaterialTheme.typography.bodyMedium.tabularNum(), color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(stringResource(R.string.split_agreement_payment_facts,
            formatDisplayAmount(agreement.originalPaidAmountCents, display),
            formatDisplayAmount(agreement.returnPaidAmountCents, display)),
            style = MaterialTheme.typography.bodyMedium.tabularNum(), color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(stringResource(R.string.split_agreement_forgiveness_facts,
            formatDisplayAmount(agreement.originalForgivenAmountCents, display),
            formatDisplayAmount(agreement.returnForgivenAmountCents, display)),
            style = MaterialTheme.typography.bodyMedium.tabularNum(), color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    Text(stringResource(R.string.split_agreement_private_records_notice),
        style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    if (agreement.originalDebt.publicId != state.task?.debtPublicId) {
        TextButton(onClick = { onOpenDebt(agreement.originalDebt.publicId) }) {
            Text(stringResource(R.string.split_agreement_open_original_debt))
        }
    }
    agreement.returnDebt?.takeIf { it.publicId != state.task?.debtPublicId }?.let { debt ->
        TextButton(onClick = { onOpenDebt(debt.publicId) }) {
            Text(stringResource(R.string.split_agreement_open_return_debt))
        }
    }
    if (agreement.pendingRepaymentDebtPublicIds.isNotEmpty()) {
        Text(stringResource(R.string.split_agreement_pending_repayments))
        agreement.pendingRepaymentDebtPublicIds.forEach { id ->
            if (id == state.task?.debtPublicId) Text(stringResource(R.string.split_agreement_current_debt_pending))
            else AppSecondaryButton(text = stringResource(R.string.split_agreement_process_declaration,
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
            formatDisplayAmount(proposal.newShareAmountCents, display)),
            style = MaterialTheme.typography.titleSmall.tabularNum())
        Text(stringResource(R.string.split_agreement_proposal_settlement,
            splitSettlementLabel(proposal.settlementNetAmountCents, display)),
            style = MaterialTheme.typography.bodyMedium.tabularNum())
        Text(proposal.reason, style = MaterialTheme.typography.bodyMedium)
        if (state.replacingProposalPublicId == proposal.publicId) {
            Text(stringResource(R.string.split_agreement_replacement_notice))
            SplitAgreementForm(state, model, display)
            AppSecondaryButton(text = stringResource(R.string.split_agreement_cancel_replacement),
                onClick = model::cancelReplacement, enabled = state.canModify && !state.busy)
        } else {
            if (!proposal.proposedByYou) {
                SplitSettlementConfirmation(state, model)
                AppPrimaryButton(text = stringResource(R.string.split_agreement_accept),
                    icon = Icons.Filled.Check, modifier = Modifier.fillMaxWidth(),
                    onClick = { model.resolve(true) },
                    enabled = state.commandsEnabled && state.previewReady && state.confirmed &&
                        agreement.pendingRepaymentDebtPublicIds.isEmpty())
            }
            AppSecondaryButton(text = stringResource(if (proposal.proposedByYou) {
                R.string.split_agreement_withdraw
            } else {
                R.string.split_agreement_reject
            }),
                onClick = { model.resolve(false) }, enabled = state.commandsEnabled)
            AppSecondaryButton(text = stringResource(R.string.split_agreement_replace),
                onClick = model::beginReplacement, enabled = state.commandsEnabled && agreement.viewerIsParty)
        }
    } ?: SplitAgreementForm(state, model, display)
}

@Composable
private fun SplitAgreementSubmissions(state: SplitAgreementUiState, model: SplitAgreementViewModel) {
    val pending = state.rows.filter { it.status != PendingMutationStatus.Done }
    if (pending.isEmpty()) return
    Text(stringResource(R.string.split_agreement_submissions_title),
        modifier = Modifier.padding(top = AppSpacing.cardGap), style = MaterialTheme.typography.titleMedium)
    pending.forEach { row ->
        Column(modifier = Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
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
                AppPrimaryButton(text = stringResource(R.string.split_agreement_retry_submission),
                    icon = Icons.Filled.Refresh, modifier = Modifier.fillMaxWidth(),
                    onClick = { model.recover(row, false) }, enabled = state.canModify)
            }
            if (row.status in setOf(PendingMutationStatus.Failed, PendingMutationStatus.Conflict)) {
                AppSecondaryButton(text = stringResource(R.string.split_agreement_end_submission),
                    modifier = Modifier.align(Alignment.End),
                    onClick = { model.recover(row, true) })
            }
        }
    }
}

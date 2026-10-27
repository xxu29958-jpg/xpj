package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.data.repository.MemberSettlementCommand
import com.ticketbox.domain.model.CurrencyDisplay
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppAmountText
import com.ticketbox.ui.components.AppFloatingActionBar
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppPaperCard
import com.ticketbox.ui.components.AppPrimaryButton
import com.ticketbox.ui.components.AppSecondaryPageChrome
import com.ticketbox.ui.components.AppSecondaryPageSlots
import com.ticketbox.ui.components.AppSecondaryRefreshState
import com.ticketbox.ui.components.AppSecondaryScrollableContent
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.presentation.formatDisplayAmount
import com.ticketbox.ui.design.AppAmountRole
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalStateTokens
import com.ticketbox.viewmodel.DebtDetailUiState
import com.ticketbox.viewmodel.MemberProposalUiState
import com.ticketbox.viewmodel.MemberRepaymentProposalViewModel

/** Reachable even when a refreshed fold/proposal list no longer offers the original action. */
@Composable
internal fun MemberOriginalSubmission(detail: DebtDetailUiState, state: MemberProposalUiState,
    viewModel: MemberRepaymentProposalViewModel, callbacks: DebtDetailScreenCallbacks) {
    val original = state.originalAttempt ?: return
    val palette = if (original.rejected) LocalStateTokens.current.danger else LocalStateTokens.current.warn
    AppSecondaryScrollableContent(
        chrome = AppSecondaryPageChrome(role = AppPageRole.Stats,
            title = stringResource(if (original.rejected) R.string.debt_payment_rejected_title else R.string.debt_payment_unknown_title),
            subtitle = stringResource(original.command.originalTitleRes()),
            backText = stringResource(R.string.debt_proposal_back_keep_draft), onBack = callbacks.onBack,
            verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap)),
        refresh = AppSecondaryRefreshState(detail.isLoading, callbacks.onRefresh),
        slots = AppSecondaryPageSlots(bottomBar = {
            MemberOriginalActions(detail.debt, state, viewModel, callbacks.onBack)
        }),
    ) {
        item {
            AppPaperCard(containerColor = palette.bg) {
                Text(stringResource(if (original.rejected) R.string.debt_proposal_original_rejected else R.string.debt_proposal_original_unknown),
                    modifier = Modifier.fillMaxWidth().padding(AppSpacing.cardPadding),
                    style = MaterialTheme.typography.bodyMedium, color = palette.fg)
            }
        }
        item { MemberOriginalContext(state) }
        if (!state.canModify) item {
            AppStatusBanner(UiText.res(R.string.debt_proposal_readonly_note), MessageTone.Info)
        }
        if (original.rejected && detail.debt == null) item {
            AppStatusBanner(detail.error, MessageTone.Danger)
            TextButton(onClick = callbacks.onRefresh, enabled = !detail.isLoading) { Text(stringResource(R.string.common_retry)) }
        }
    }
}

@Composable
private fun MemberOriginalActions(debt: Debt?, state: MemberProposalUiState,
    viewModel: MemberRepaymentProposalViewModel, onBack: () -> Unit) {
    val original = state.originalAttempt ?: return
    val task = state.task ?: return
    AppFloatingActionBar {
        Column(verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap)) {
            AppPrimaryButton(text = stringResource(if (original.rejected) R.string.debt_proposal_review_rejected else R.string.debt_proposal_retry_original),
                modifier = Modifier.fillMaxWidth(), enabled = state.canReviewOrRetryOriginal(debt != null), onClick = {
                    if (original.rejected) debt?.let { viewModel.reviewRejected(task, it) } else viewModel.retryOriginal(task)
                })
            TextButton(onClick = onBack, enabled = !state.isSubmitting, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.debt_proposal_back_keep_draft))
            }
        }
    }
}

private fun MemberProposalUiState.canReviewOrRetryOriginal(hasCurrentDebt: Boolean): Boolean =
    canModify && !isSubmitting && (originalAttempt?.rejected != true || hasCurrentDebt)

@Composable
private fun MemberOriginalContext(state: MemberProposalUiState) {
    val amount = when (val command = state.originalAttempt?.command) {
        is MemberSettlementCommand.Propose -> command.amountCents
        is MemberSettlementCommand.Confirm -> command.amountCents ?: state.formProposedAmount
        else -> null
    }
    AppPaperCard {
        Column(Modifier.fillMaxWidth().padding(AppSpacing.cardPadding), verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap)) {
            Text(stringResource(R.string.debt_payment_original_amount), style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant)
            amount?.let { AppAmountText(formatDisplayAmount(it, CurrencyDisplay.forRecord(state.formCurrencyCode)), role = AppAmountRole.Hero) }
            state.formCurrencyCode?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
            state.paymentTime?.date?.takeIf { it.isNotBlank() }?.let { Text(stringResource(R.string.debt_payment_original_date, it)) }
            state.originalContext?.counterpartyLabel?.let { label ->
                Text(stringResource(when (state.originalContext.viewerIsDebtor) {
                    true -> R.string.debt_proposal_original_debtor
                    false -> R.string.debt_proposal_original_creditor
                    null -> R.string.debt_proposal_original_party
                }, label))
            }
            if (state.noteInput.isNotBlank()) Text(state.noteInput)
        }
    }
}

private fun MemberSettlementCommand.originalTitleRes(): Int = when (this) {
    is MemberSettlementCommand.Propose -> R.string.debt_proposal_propose_title
    is MemberSettlementCommand.Confirm -> R.string.debt_proposal_confirm_title
    is MemberSettlementCommand.Withdraw -> R.string.debt_proposal_withdraw_action
    is MemberSettlementCommand.Reject -> R.string.debt_proposal_reject_action
    is MemberSettlementCommand.Forgive -> R.string.debt_member_forgive_action
}

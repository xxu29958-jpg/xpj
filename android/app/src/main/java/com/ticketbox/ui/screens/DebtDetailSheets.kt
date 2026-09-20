package com.ticketbox.ui.screens

import androidx.compose.runtime.Composable
import com.ticketbox.viewmodel.DebtDetailUiState
import com.ticketbox.viewmodel.MemberProposalUiState
import com.ticketbox.viewmodel.MemberRepaymentProposalViewModel

@Composable
internal fun DebtMemberProposalForm(
    state: DebtDetailUiState,
    proposalState: MemberProposalUiState,
    proposalViewModel: MemberRepaymentProposalViewModel,
) {
    val debt = state.debt
    if (debt?.isMember == true && proposalState.activeForm != null) {
        ProposalFormSheet(
            state = proposalState,
            viewModel = proposalViewModel,
            debt = debt,
            onClose = { proposalState.task?.let(proposalViewModel::dismissForm) },
        )
    }
}

package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.viewmodel.CreateDebtGoalViewModel
import com.ticketbox.viewmodel.DebtDetailViewModel
import com.ticketbox.viewmodel.DebtGoalViewModel
import com.ticketbox.viewmodel.MemberRepaymentProposalViewModel
import com.ticketbox.viewmodel.createDebtGoalViewModelFactory
import com.ticketbox.viewmodel.debtDetailViewModelFactory
import com.ticketbox.viewmodel.debtGoalViewModelFactory
import com.ticketbox.viewmodel.memberRepaymentProposalViewModelFactory

internal data class DebtGoalRouteViewModels(
    val debtGoal: DebtGoalViewModel,
    val createGoal: CreateDebtGoalViewModel,
    val linkedDetail: DebtDetailViewModel,
    val linkedProposal: MemberRepaymentProposalViewModel,
)

@Composable
internal fun rememberDebtGoalRouteViewModels(screenFactory: MainScreenFactory): DebtGoalRouteViewModels =
    DebtGoalRouteViewModels(
        debtGoal = viewModel(
            key = DebtGoalViewModelKey,
            factory = debtGoalViewModelFactory(screenFactory.reportsRepository),
        ),
        createGoal = viewModel(
            key = CreateDebtGoalViewModelKey,
            factory = createDebtGoalViewModelFactory(
                screenFactory.reportsRepository,
                screenFactory.debtRepository,
            ),
        ),
        linkedDetail = viewModel(
            key = DebtGoalLinkedDetailViewModelKey,
            factory = debtDetailViewModelFactory(screenFactory.debtRepository),
        ),
        linkedProposal = viewModel(
            key = DebtGoalLinkedProposalViewModelKey,
            factory = memberRepaymentProposalViewModelFactory(screenFactory.debtRepository.proposals),
        ),
    )

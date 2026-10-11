package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.lifecycle.ViewModelStoreOwner
import com.ticketbox.viewmodel.CreateDebtGoalViewModel
import com.ticketbox.viewmodel.DebtDetailViewModel
import com.ticketbox.viewmodel.DebtGoalViewModel
import com.ticketbox.viewmodel.DebtActivityViewModel
import com.ticketbox.viewmodel.MemberRepaymentProposalViewModel
import com.ticketbox.viewmodel.createDebtGoalViewModelFactory
import com.ticketbox.viewmodel.debtDetailViewModelFactory
import com.ticketbox.viewmodel.debtGoalViewModelFactory
import com.ticketbox.viewmodel.debtActivityViewModelFactory
import com.ticketbox.viewmodel.memberRepaymentProposalViewModelFactory

internal data class DebtGoalRouteViewModels(
    val debtGoal: DebtGoalViewModel,
    val createGoal: CreateDebtGoalViewModel,
    val links: com.ticketbox.viewmodel.DebtGoalEditViewModel,
    val date: com.ticketbox.viewmodel.DebtGoalEditViewModel,
    val linked: DebtDetailHostModels,
)

@Composable
internal fun rememberDebtGoalRouteViewModels(screenFactory: MainScreenFactory, creationOwner: ViewModelStoreOwner): DebtGoalRouteViewModels =
    DebtGoalRouteViewModels(
        debtGoal = viewModel(
            key = DebtGoalViewModelKey,
            factory = debtGoalViewModelFactory(screenFactory.reportsRepository, screenFactory.debtWriteRepository),
        ),
        createGoal = viewModel(
            viewModelStoreOwner = creationOwner,
            key = CreateDebtGoalViewModelKey,
            factory = createDebtGoalViewModelFactory(
                screenFactory.goalEditRepository,
                screenFactory.debtRepository,
                screenFactory.debtWriteRepository,
            ),
        ),
        links = viewModel(viewModelStoreOwner = creationOwner, key = "debt-goal-links",
            factory = com.ticketbox.viewmodel.debtGoalEditViewModelFactory(screenFactory.reportsRepository,
                screenFactory.goalEditRepository, screenFactory.debtRepository)),
        date = viewModel(viewModelStoreOwner = creationOwner, key = "debt-goal-date",
            factory = com.ticketbox.viewmodel.debtGoalEditViewModelFactory(screenFactory.reportsRepository,
                screenFactory.goalEditRepository, screenFactory.debtRepository, com.ticketbox.viewmodel.DebtGoalEditKind.TargetDate)),
        linked = DebtDetailHostModels(detail = viewModel(
            key = DebtGoalLinkedDetailViewModelKey,
            factory = debtDetailViewModelFactory(screenFactory.debtRepository, screenFactory.debtWriteRepository),
        ),
        proposal = viewModel(
            key = DebtGoalLinkedProposalViewModelKey,
            factory = memberRepaymentProposalViewModelFactory(screenFactory.debtRepository.proposals),
        ),
        history = viewModel(
            key = DebtGoalLinkedRepaymentHistoryViewModelKey,
            factory = debtActivityViewModelFactory(screenFactory.debtActivityRepository),
        )),
    )

internal data class DebtDetailHostModels(
    val detail: DebtDetailViewModel,
    val proposal: MemberRepaymentProposalViewModel,
    val history: DebtActivityViewModel,
)

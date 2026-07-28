package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.ui.screens.plan.PlanScreen
import com.ticketbox.ui.screens.plan.PlanScreenActions
import com.ticketbox.ui.screens.plan.PlanBudgetNavigationActions
import com.ticketbox.ui.screens.plan.PlanScreenData
import com.ticketbox.viewmodel.BudgetViewModel
import com.ticketbox.viewmodel.IncomePlanViewModel
import com.ticketbox.viewmodel.RecurringViewModel
import com.ticketbox.viewmodel.budgetViewModelFactory
import com.ticketbox.viewmodel.incomePlanViewModelFactory
import com.ticketbox.viewmodel.recurringViewModelFactory

@Composable
internal fun PlanRoute(
    shellState: MainShellState,
    screenFactory: MainScreenFactory,
) {
    val budgetViewModel: BudgetViewModel = viewModel(
        factory = budgetViewModelFactory(screenFactory.budgetRepository, screenFactory.debtRepository),
    )
    val recurringViewModel: RecurringViewModel = viewModel(
        factory = recurringViewModelFactory(screenFactory.recurringRepository),
    )
    val incomePlanViewModel: IncomePlanViewModel = viewModel(
        factory = incomePlanViewModelFactory(screenFactory.incomePlanRepository, screenFactory.debtRepository),
    )
    val budgetState by budgetViewModel.uiState.collectAsStateWithLifecycle()
    val recurringState by recurringViewModel.uiState.collectAsStateWithLifecycle()
    val incomeState by incomePlanViewModel.state.collectAsStateWithLifecycle()
    var appliedPlanDataRevision by rememberSaveable {
        mutableIntStateOf(shellState.planDataRevision)
    }

    LaunchedEffect(shellState.planDataRevision) {
        if (appliedPlanDataRevision != shellState.planDataRevision) {
            refreshPlanOverview(
                budget = budgetViewModel,
                recurring = recurringViewModel,
                income = incomePlanViewModel,
            )
            appliedPlanDataRevision = shellState.planDataRevision
        }
    }

    PlanScreen(
        data = PlanScreenData(
            budget = budgetState,
            recurring = recurringState,
            income = incomeState,
        ),
        actions = PlanScreenActions(
            budgetNavigation = PlanBudgetNavigationActions(
                onOpenBudget = { shellState.openSecondaryPage(ProductSecondaryPage.Budget) },
                onOpenAdvice = { shellState.openSecondaryPage(ProductSecondaryPage.BudgetAdvice) },
            ),
            onOpenSpendingGoal = { shellState.openSecondaryPage(ProductSecondaryPage.SpendingGoal) },
            onOpenRecurring = { shellState.openSecondaryPage(ProductSecondaryPage.Recurring) },
            onOpenIncomePlans = { shellState.openSecondaryPage(ProductSecondaryPage.IncomePlans) },
            onRefresh = {
                refreshPlanOverview(
                    budget = budgetViewModel,
                    recurring = recurringViewModel,
                    income = incomePlanViewModel,
                )
            },
        ),
    )
}

private fun refreshPlanOverview(
    budget: BudgetViewModel,
    recurring: RecurringViewModel,
    income: IncomePlanViewModel,
) {
    budget.refresh()
    recurring.refresh()
    income.refresh()
}

package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.ui.screens.plan.PlanScreen
import com.ticketbox.ui.screens.plan.PlanScreenActions
import com.ticketbox.ui.screens.plan.PlanBudgetNavigationActions
import com.ticketbox.ui.screens.plan.PlanScreenData
import com.ticketbox.viewmodel.BudgetViewModel
import com.ticketbox.viewmodel.IncomePlanViewModel
import com.ticketbox.viewmodel.RecurringViewModel
import com.ticketbox.viewmodel.SpendingGoalsViewModel
import com.ticketbox.viewmodel.budgetViewModelFactory
import com.ticketbox.viewmodel.incomePlanViewModelFactory
import com.ticketbox.viewmodel.recurringViewModelFactory
import com.ticketbox.viewmodel.spendingGoalsViewModelFactory

@Composable
internal fun PlanRoute(
    shellState: MainShellState,
    screenFactory: MainScreenFactory,
) {
    val budgetViewModel: BudgetViewModel = viewModel(
        factory = budgetViewModelFactory(screenFactory.budgetRepository, calendars = screenFactory.repositories.ledgerCalendarRepository),
    )
    val recurringViewModel: RecurringViewModel = viewModel(
        factory = recurringViewModelFactory(screenFactory.recurringRepository),
    )
    val incomePlanViewModel: IncomePlanViewModel = viewModel(
        factory = incomePlanViewModelFactory(screenFactory.incomePlanRepository),
    )
    // 状态卡的消费目标读数：与目标页同一读取，按当前账本月份。
    val goalsViewModel: SpendingGoalsViewModel = viewModel(
        factory = spendingGoalsViewModelFactory(screenFactory.reportsRepository, screenFactory.goalEditRepository,
            screenFactory.repositories.ledgerCalendarRepository),
    )
    val budgetState by budgetViewModel.uiState.collectAsStateWithLifecycle()
    val recurringState by recurringViewModel.uiState.collectAsStateWithLifecycle()
    val incomeState by incomePlanViewModel.state.collectAsStateWithLifecycle()
    val goalsState by goalsViewModel.state.collectAsStateWithLifecycle()
    LaunchedEffect(shellState.financialDataRevision) {
        if (shellState.financialDataRevision > 0) {
            refreshPlanOverview(
                budget = budgetViewModel,
                recurring = recurringViewModel,
                income = incomePlanViewModel,
                goals = goalsViewModel,
                invalidateRecurring = true,
            )
        }
    }

    PlanScreen(
        data = PlanScreenData(
            budget = budgetState,
            recurring = recurringState,
            income = incomeState,
            goals = goalsState,
        ),
        actions = PlanScreenActions(
            budgetNavigation = PlanBudgetNavigationActions(
                onOpenBudget = { shellState.openBudget(budgetState.month) },
                onOpenAdvice = { shellState.openSecondaryPage(ProductSecondaryPage.BudgetAdvice) },
            ),
            onOpenSpendingGoal = { shellState.openSecondaryPage(ProductSecondaryPage.SpendingGoal) },
            onOpenDebtGoal = { shellState.openSecondaryPage(ProductSecondaryPage.DebtGoals) },
            onOpenRecurring = { shellState.openSecondaryPage(ProductSecondaryPage.Recurring) },
            onOpenIncomePlans = { shellState.openSecondaryPage(ProductSecondaryPage.IncomePlans) },
            onRefresh = {
                refreshPlanOverview(
                    budget = budgetViewModel,
                    recurring = recurringViewModel,
                    income = incomePlanViewModel,
                    goals = goalsViewModel,
                )
            },
        ),
    )
}

private fun refreshPlanOverview(
    budget: BudgetViewModel,
    recurring: RecurringViewModel,
    income: IncomePlanViewModel,
    goals: SpendingGoalsViewModel,
    invalidateRecurring: Boolean = false,
) {
    budget.refresh()
    recurring.refresh(retireCurrent = invalidateRecurring)
    income.refresh()
    goals.refresh()
}

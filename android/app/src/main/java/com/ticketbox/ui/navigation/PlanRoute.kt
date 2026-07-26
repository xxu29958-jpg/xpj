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
        key = planViewModelKey("plan-budget", screenFactory.ledgerRepository.activeLedgerId()),
        factory = budgetViewModelFactory(screenFactory.budgetRepository),
    )
    val recurringViewModel: RecurringViewModel = viewModel(
        key = planViewModelKey("plan-recurring", screenFactory.ledgerRepository.activeLedgerId()),
        factory = recurringViewModelFactory(screenFactory.recurringRepository),
    )
    val incomePlanViewModel: IncomePlanViewModel = viewModel(
        key = planViewModelKey("plan-income", screenFactory.ledgerRepository.activeLedgerId()),
        factory = incomePlanViewModelFactory(screenFactory.incomePlanRepository),
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

/**
 * Ledger-scoped ViewModel key for the Plan overview, mirroring
 * [transactionsLibraryViewModelKey] (218-B2): keying by active ledger
 * guarantees a fresh VM (fresh load) after a ledger switch instead of reusing
 * the previous ledger's budget / recurring / income state from the back stack.
 */
internal fun planViewModelKey(prefix: String, ledgerId: String?): String =
    "$prefix-${ledgerId ?: "none"}"

private fun refreshPlanOverview(
    budget: BudgetViewModel,
    recurring: RecurringViewModel,
    income: IncomePlanViewModel,
) {
    budget.refresh()
    recurring.refresh()
    income.refresh()
}

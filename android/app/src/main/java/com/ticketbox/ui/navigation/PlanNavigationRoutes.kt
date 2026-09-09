package com.ticketbox.ui.navigation

import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavType
import androidx.navigation.compose.composable
import androidx.navigation.navArgument

internal fun spendingGoalEditRoute(id: String): String = "${ProductSecondaryPage.SpendingGoal.route}?goal=${android.net.Uri.encode(id)}"

internal fun spendingGoalCreationRoute(id: Long): String = "${ProductSecondaryPage.SpendingGoal.route}?create=$id"

internal fun incomePlanSubmissionRoute(id: Long): String = "${ProductSecondaryPage.IncomePlans.route}?submission=$id"
internal fun budgetAdviceSubmissionRoute(id: Long): String = "${ProductSecondaryPage.BudgetAdvice.route}?submission=$id"

internal fun budgetRoute(month: String): String = "${ProductSecondaryPage.Budget.route}?month=$month"

internal fun NavGraphBuilder.addPlanRoutes(
    dependencies: MainProductRouteDependencies,
) {
    with(dependencies) {
        val onAdviceInputChanged = {
            markPlanWriteCompleted(shellState, invalidatesAdvice = true) {
                screenFactory.budgetRepository.invalidateBudgetAdvice()
            }
        }
        composable(route = "${ProductSecondaryPage.SpendingGoal.route}?create={create}&goal={goal}",
            arguments = listOf(navArgument("create") { type = NavType.StringType; nullable = true; defaultValue = null },
                navArgument("goal") { type = NavType.StringType; nullable = true; defaultValue = null }),
        ) { entry ->
            SpendingGoalsRoute(
                originalCreationId = entry.arguments?.getString("create")?.toLongOrNull(),
                originalGoalPublicId = entry.arguments?.getString("goal"),
                screenFactory = screenFactory,
                onBack = onBack,
            )
        }
        composable(
            route = budgetRoute("{month}"),
            arguments = listOf(navArgument("month") { type = NavType.StringType; nullable = true; defaultValue = null }),
        ) {
            BudgetRoute(
                screenFactory = screenFactory,
                onBack = onBack,
                // The monthly-budget row is NOT an advisor input
                // (_inputs_builder.py) — a budget save must not invalidate.
                onDataChanged = shellState::markPlanDataChanged,
            )
        }
        composable("${ProductSecondaryPage.BudgetAdvice.route}?submission={submission}",
            arguments = listOf(navArgument("submission") { type = NavType.StringType; nullable = true; defaultValue = null })) { entry ->
            BudgetAdviceRoute(
                screenFactory = screenFactory,
                onBack = onBack,
                originalSubmissionId = entry.arguments?.getString("submission")?.toLongOrNull(),
            )
        }
        composable(ProductSecondaryPage.Recurring.route) {
            RecurringRoute(
                screenFactory = screenFactory,
                onBack = onBack,
                onOpenExpense = runtime.navController::openExpense,
                onDataChanged = onAdviceInputChanged,
            )
        }
        composable(route = "${ProductSecondaryPage.IncomePlans.route}?submission={submission}",
            arguments = listOf(navArgument("submission") { type = NavType.StringType; nullable = true; defaultValue = null }),
        ) { entry ->
            IncomePlanRoute(
                originalSubmissionId = entry.arguments?.getString("submission")?.toLongOrNull(),
                screenFactory = screenFactory,
                onBack = onBack,
                onDataChanged = onAdviceInputChanged,
            )
        }
    }
}

/** Plan-write refresh composition: every plan save bumps the plan revision;
 *  only saves that feed the budget-advisor inputs (income plans, recurring —
 *  NOT the monthly-budget row, see _inputs_builder.py) also drop the
 *  process-lifetime advice cache, so a reopened advice page recomputes
 *  instead of restoring pre-write limits without wasting quota on no-ops. */
internal fun markPlanWriteCompleted(
    shellState: MainShellState,
    invalidatesAdvice: Boolean,
    invalidateBudgetAdvice: () -> Unit,
) {
    shellState.markPlanDataChanged()
    if (invalidatesAdvice) {
        invalidateBudgetAdvice()
    }
}


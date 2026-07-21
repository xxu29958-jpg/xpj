package com.ticketbox.ui.navigation

import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.composable
import androidx.navigation.navArgument

internal class MainProductRouteDependencies(
    val runtime: MainNavigationRuntime,
    val navController: NavHostController,
    val workspaceControls: MainWorkspaceControls,
) {
    val shellState: MainShellState = runtime.shellState
    val screenFactory: MainScreenFactory = runtime.screenFactory
    val onBack: () -> Unit = { navController.popBackStack() }
}

internal fun NavGraphBuilder.addPrimaryDomainRoutes(
    dependencies: MainProductRouteDependencies,
) {
    with(dependencies) {
        composable(PrimaryDomain.Inbox.route) {
            PendingRoute(
                navController = runtime.navController,
                shellState = shellState,
                screenFactory = screenFactory,
            )
        }
        composable(PrimaryDomain.Transactions.route) {
            LedgerRoute(
                navController = runtime.navController,
                shellState = shellState,
                screenFactory = screenFactory,
            )
        }
        composable(PrimaryDomain.Obligations.route) {
            RelationsRoute(
                shellState = shellState,
                screenFactory = screenFactory,
            )
        }
        composable(PrimaryDomain.Plans.route) {
            PlanRoute(
                shellState = shellState,
                screenFactory = screenFactory,
            )
        }
        composable(PrimaryDomain.Insights.route) {
            StatsRoute(
                shellState = shellState,
                screenFactory = screenFactory,
            )
        }
    }
}

internal fun NavGraphBuilder.addWorkspaceRoute(
    dependencies: MainProductRouteDependencies,
) {
    with(dependencies) {
        composable(WORKSPACE_ROUTE) {
            SettingsRoute(
                screenFactory = screenFactory,
                preferenceControls = workspaceControls.preferences,
                onBindingCleared = workspaceControls.onBindingCleared,
                onClose = onBack,
            )
        }
    }
}

internal fun NavGraphBuilder.addInboxRoutes(
    dependencies: MainProductRouteDependencies,
) {
    with(dependencies) {
        composable(ProductSecondaryPage.InboxProcessing.route) {
            InboxProcessingRoute(
                screenFactory = screenFactory,
                onBack = onBack,
            )
        }
    }
}

internal fun NavGraphBuilder.addPlanRoutes(
    dependencies: MainProductRouteDependencies,
) {
    with(dependencies) {
        composable(ProductSecondaryPage.SpendingGoal.route) {
            SpendingGoalsRoute(
                screenFactory = screenFactory,
                onBack = onBack,
            )
        }
        composable(ProductSecondaryPage.Budget.route) {
            BudgetRoute(
                screenFactory = screenFactory,
                onBack = onBack,
                onDataChanged = shellState::markPlanDataChanged,
            )
        }
        // 218-B1: 预算建议屏属后续 slice（BudgetAdviceScreen 未随骨架迁入），枚举保留但暂不挂路由。
        composable(ProductSecondaryPage.Recurring.route) {
            RecurringRoute(
                screenFactory = screenFactory,
                onBack = onBack,
                onDataChanged = shellState::markPlanDataChanged,
            )
        }
        composable(ProductSecondaryPage.IncomePlans.route) {
            IncomePlanRoute(
                screenFactory = screenFactory,
                onBack = onBack,
                onDataChanged = shellState::markPlanDataChanged,
            )
        }
    }
}

internal fun NavGraphBuilder.addInsightsRoutes(
    dependencies: MainProductRouteDependencies,
) {
    // 218-B1: 数据质量屏属后续 slice；入口（洞察页 DataQualityEntryCard / 收件链接）
    // 由 StatsRouteActions / PendingRoute 重定向到带筛选的 Inbox，这里不挂路由。
}

internal fun NavGraphBuilder.addTransactionRoutes(
    dependencies: MainProductRouteDependencies,
) {
    with(dependencies) {
        composable(ProductSecondaryPage.GlobalSearch.route) {
            SearchRoute(
                navController = runtime.navController,
                screenFactory = screenFactory,
                onBack = onBack,
            )
        }
        transactionsLibraryGraph(
            navController = navController,
            screenFactory = screenFactory,
            onVocabularyChanged = shellState::markTransactionVocabularyChanged,
            onRestoreCompleted = shellState::markRecycleBinRestoreCompleted,
        )
    }
}

internal fun NavGraphBuilder.addObligationRoutes(
    dependencies: MainProductRouteDependencies,
) {
    with(dependencies) {
        composable(ProductSecondaryPage.BillSplits.route) {
            BillSplitRoute(
                screenFactory = screenFactory,
                onBack = onBack,
            )
        }
        composable(ProductSecondaryPage.DebtGoals.route) {
            DebtGoalRoute(
                screenFactory = screenFactory,
                onBack = onBack,
            )
        }
        composable(
            route = REPAYMENT_DRAFT_ROUTE,
            arguments = listOf(
                navArgument(REPAYMENT_DRAFT_FOCUS_ARG) {
                    type = NavType.StringType
                    nullable = true
                    defaultValue = null
                },
            ),
        ) { entry ->
            RepaymentDraftRoute(
                screenFactory = screenFactory,
                focusedDraftPublicId = entry.arguments?.getString(REPAYMENT_DRAFT_FOCUS_ARG),
                onBack = onBack,
            )
        }
    }
}

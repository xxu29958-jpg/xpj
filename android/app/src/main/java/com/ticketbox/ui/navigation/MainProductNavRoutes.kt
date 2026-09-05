package com.ticketbox.ui.navigation

import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.composable
import androidx.navigation.navArgument
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.viewmodel.compose.viewModel
import com.ticketbox.R
import com.ticketbox.domain.model.DebtListLens
import com.ticketbox.ui.screens.RelationsListChrome
import com.ticketbox.ui.screens.settings.SyncStatusScreen
import com.ticketbox.viewmodel.OutboxStatusViewModel
import com.ticketbox.viewmodel.outboxStatusViewModelFactory

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
                // The monthly-budget row is NOT an advisor input
                // (_inputs_builder.py) — a budget save must not invalidate.
                onDataChanged = {
                    markPlanWriteCompleted(shellState, invalidatesAdvice = false) {
                        screenFactory.budgetRepository.invalidateBudgetAdvice()
                    }
                },
            )
        }
        composable(ProductSecondaryPage.BudgetAdvice.route) {
            BudgetAdviceRoute(
                screenFactory = screenFactory,
                onBack = onBack,
            )
        }
        composable(ProductSecondaryPage.Recurring.route) {
            RecurringRoute(
                screenFactory = screenFactory,
                onBack = onBack,
                onDataChanged = {
                    markPlanWriteCompleted(shellState, invalidatesAdvice = true) {
                        screenFactory.budgetRepository.invalidateBudgetAdvice()
                    }
                },
            )
        }
        composable(ProductSecondaryPage.IncomePlans.route) {
            IncomePlanRoute(
                screenFactory = screenFactory,
                onBack = onBack,
                onDataChanged = {
                    markPlanWriteCompleted(shellState, invalidatesAdvice = true) {
                        screenFactory.budgetRepository.invalidateBudgetAdvice()
                    }
                },
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

internal fun NavGraphBuilder.addInsightsRoutes(
    dependencies: MainProductRouteDependencies,
) {
    with(dependencies) {
        composable(ProductSecondaryPage.InsightsDataQuality.route) { currentEntry ->
            DataQualityRoute(
                navController = navController,
                currentEntry = currentEntry,
                screenFactory = screenFactory,
                shellState = shellState,
                onBack = onBack,
            )
        }
    }
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
            // 回收站恢复覆盖 monthly_budget / income_plan / recurring_item 等建议
            // 输入实体（kind 见 backend recycle_bin_service），与流水恢复同点失效建议缓存。
            onRestoreCompleted = {
                shellState.markRecycleBinRestoreCompleted()
                screenFactory.budgetRepository.invalidateBudgetAdvice()
            },
            // 规则应用/回滚与回收站 tag_mutation 恢复会原地改写确认流水行——语义
            // 等同批量流水编辑完成，复用 expenseEditCompletionRevision 通道让账本
            // 行重同步（同时失效洞察汇总）。这些写入也改变建议输入，一并失效建议缓存。
            onTransactionRowsChanged = {
                shellState.markExpenseEditCompleted()
                screenFactory.budgetRepository.invalidateBudgetAdvice()
            },
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
        // 全账本往来二级页（W2-C）：ledger lens 的完整账本视图，标题带当前账本名。
        composable(ProductSecondaryPage.AllDebts.route) {
            DebtRoute(
                screenFactory = screenFactory,
                actions = DebtRouteActions(
                    onBack = onBack,
                    onOpenSyncStatus = { shellState.openSecondaryPage(ProductSecondaryPage.ObligationSync) },
                ),
                lens = DebtListLens.Ledger,
                chromeOverride = RelationsListChrome(
                    title = stringResource(R.string.relations_all_debts),
                    subtitle = screenFactory.ledgerRepository.currentLedgerName(),
                    backText = stringResource(R.string.debt_list_topbar_back),
                    onBack = onBack,
                ),
            )
        }
        composable(ProductSecondaryPage.ObligationSync.route) {
            val vm: OutboxStatusViewModel = viewModel(
                factory = outboxStatusViewModelFactory(screenFactory.outboxRepository, screenFactory.repository),
            )
            SyncStatusScreen(viewModel = vm, onBack = onBack)
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

package com.ticketbox.ui.navigation

import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.composable
import androidx.navigation.navArgument
import androidx.compose.ui.res.stringResource
import androidx.compose.runtime.remember
import androidx.compose.runtime.LaunchedEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
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
        composable(PrimaryDomain.Obligations.route) { entry ->
            RelationsRoute(
                shellState = shellState,
                screenFactory = screenFactory,
                creationOwner = remember(runtime.navController, entry) { runtime.navController.getBackStackEntry(MAIN_ROUTE) },
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
                onRepairReport = { context -> navController.navigate(reportRateRoute(context)) },
            )
        }
    }
}

internal fun NavGraphBuilder.addWorkspaceRoute(
    dependencies: MainProductRouteDependencies,
) {
    with(dependencies) {
        composable("$WORKSPACE_ROUTE?$NOTIFICATION_QUERY", arguments = listOf(notificationArgument)) { entry ->
            NotificationTaskBoundary(entry, screenFactory, onBack) {
            SettingsRoute(
                navigation = SettingsDestinationNavigation(
                    onOpenFunds = { shellState.openSecondaryPage(ProductSecondaryPage.Funds) },
                    initialDestination = if (LocalNotificationTask.current?.destination == com.ticketbox.notification.NotificationDestination.Backup)
                        com.ticketbox.ui.screens.settings.SettingsRoute.Server else com.ticketbox.ui.screens.settings.SettingsRoute.Root,
                    onOpenExpense = runtime.navController::openExpense,
                    onOpenInbox = { shellState.openPrimaryDomainRoot(PrimaryDomain.Inbox) },
                    onOpenBudget = { month -> navController.navigate(budgetRoute(month)) },
                    onOpenArrangement = { month -> navController.navigate(monthlyArrangementRoute(month)) },
                    onOpenGoalCreation = { original -> navController.navigate(goalCreationRoute(original)) },
                    onOpenGoalEdit = { original -> navController.navigate(goalEditRoute(original.row.targetId.removePrefix("goal:"), original.row.type)) },
                    onOpenRuleSubmission = { id -> navController.navigate(categoryRuleSubmissionRoute(id)) },
                    onOpenIncomeSubmission = { id -> navController.navigate(incomePlanSubmissionRoute(id)) },
                    onOpenRateSubmission = { id -> navController.navigate(budgetAdviceSubmissionRoute(id)) },
                    onRepairCorrectionRate = { binding, gap -> navController.navigate(correctionRateRoute(binding, gap)) },
                    onOpenRecurring = { shellState.openSecondaryPage(ProductSecondaryPage.Recurring) }, onCloseRoot = onBack),
                screenFactory = screenFactory,
                preferenceControls = workspaceControls.preferences,
                onBindingCleared = workspaceControls.onBindingCleared,
            )
            }
        }
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
        composable(ProductSecondaryPage.AccountingDates.route) {
            AccountingDateReviewRoute(runtime.navController, shellState, screenFactory, onBack)
        }
        composable(ProductSecondaryPage.GlobalSearch.route) {
            SearchRoute(
                navController = runtime.navController,
                screenFactory = screenFactory,
                onOpenSavedQuery = { route -> navController.navigate(route) },
                onBack = onBack,
            )
        }
        savedQueryRoute(dependencies)
        transactionsLibraryGraph(
            navController = navController,
            screenFactory = screenFactory,
            creationOwner = { runtime.navController.getBackStackEntry(MAIN_ROUTE) },
            writes = TransactionsLibraryWrites(
                vocabularyChanged = shellState::markTransactionVocabularyChanged,
                // Restored plans and financial rows also invalidate advice inputs.
                restoreCompleted = {
                    shellState.markRecycleBinRestoreCompleted()
                    screenFactory.budgetRepository.invalidateBudgetAdvice()
                },
                // Rule application and tag restoration revise existing financial rows.
                transactionRowsChanged = {
                    shellState.markExpenseEditCompleted()
                    screenFactory.budgetRepository.invalidateBudgetAdvice()
                },
            ),
        )
    }
}

internal fun NavGraphBuilder.addObligationRoutes(
    dependencies: MainProductRouteDependencies,
) {
    with(dependencies) {
        composable(ProductSecondaryPage.Funds.route + "?account={account}&capture={capture}",
            arguments = listOf(navArgument("account") { type = NavType.StringType; nullable = true; defaultValue = null },
                navArgument("capture") { type = NavType.StringType; nullable = true; defaultValue = null })) { entry ->
            val model: com.ticketbox.viewmodel.FundsViewModel = androidx.lifecycle.viewmodel.compose.viewModel(
                factory = object : androidx.lifecycle.ViewModelProvider.Factory {
                    @Suppress("UNCHECKED_CAST")
                    override fun <T : androidx.lifecycle.ViewModel> create(modelClass: Class<T>): T =
                        com.ticketbox.viewmodel.FundsViewModel(screenFactory.fundsRepository,
                            repaymentDraftId = entry.arguments?.getString("capture"), captures = screenFactory.repaymentDraftRepository) as T
                })
            val binding = model.state.value.access?.binding
            val accountId = entry.arguments?.getString("account")
            LaunchedEffect(binding, accountId) { if (binding != null && accountId != null) model.open(accountId) }
            androidx.lifecycle.compose.LifecycleEventEffect(androidx.lifecycle.Lifecycle.Event.ON_RESUME) { model.refresh() }
            LaunchedEffect(shellState.financialDataRevision) {
                if (entry.lifecycle.currentState.isAtLeast(androidx.lifecycle.Lifecycle.State.RESUMED)) model.refresh()
            }
            com.ticketbox.ui.screens.FundsScreen(model, onBack, runtime.navController::openExpense)
        }
        composable(ProductSecondaryPage.BillSplits.route) { entry ->
            val draftOwner = remember(runtime.navController, entry) { runtime.navController.getBackStackEntry(MAIN_ROUTE) }
            BillSplitRoute(screenFactory = screenFactory, draftOwner = draftOwner, onBack = onBack,
                onOpenExpense = runtime.navController::openExpense)
        }
        composable("${ProductSecondaryPage.DebtGoals.route}?create={create}&links={links}&date={date}",
            arguments = listOf(navArgument("create") { type = NavType.StringType; nullable = true; defaultValue = null },
                navArgument("links") { type = NavType.StringType; nullable = true; defaultValue = null },
                navArgument("date") { type = NavType.StringType; nullable = true; defaultValue = null })) { entry ->
            val creationOwner = remember(runtime.navController, entry) { runtime.navController.getBackStackEntry(MAIN_ROUTE) }
            DebtGoalRoute(
                screenFactory = screenFactory,
                onBack = onBack,
                context = DebtGoalRouteContext(creationOwner,
                    originalCreationId = entry.arguments?.getString("create")?.toLongOrNull(),
                    originalLinksId = entry.arguments?.getString("links"), originalDateId = entry.arguments?.getString("date"),
                    financialDataRevision = shellState.financialDataRevision),
                onOpenRecycleBin = { navController.navigate(TRANSACTIONS_LIBRARY_RECYCLE_BIN_ROUTE) },
                onOpenCredit = shellState::openCreditAccount,
            )
        }
        // 全账本往来二级页（W2-C）：ledger lens 的完整账本视图，标题带当前账本名。
        composable(ProductSecondaryPage.AllDebts.route) { entry ->
            DebtRoute(
                screenFactory = screenFactory,
                context = DebtRouteContext(
                    onBack = onBack,
                    onOpenSyncStatus = { shellState.openSecondaryPage(ProductSecondaryPage.ObligationSync) },
                    onOpenCredit = shellState::openCreditAccount,
                    creationOwner = remember(runtime.navController, entry) { runtime.navController.getBackStackEntry(MAIN_ROUTE) },
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
        addObligationSyncRoute(dependencies)
        addRepaymentDraftRoute(dependencies)
    }
}

private fun NavGraphBuilder.addRepaymentDraftRoute(dependencies: MainProductRouteDependencies) {
    with(dependencies) {
        composable(
            route = "$REPAYMENT_DRAFT_ROUTE&$NOTIFICATION_QUERY",
            arguments = listOf(notificationArgument,
                navArgument(REPAYMENT_DRAFT_FOCUS_ARG) {
                    type = NavType.StringType
                    nullable = true
                    defaultValue = null
                },
            ),
        ) { entry ->
            NotificationTaskBoundary(entry, screenFactory, onBack) {
                RepaymentDraftRoute(
                    screenFactory = screenFactory,
                    focusedDraftPublicId = entry.arguments?.getString(REPAYMENT_DRAFT_FOCUS_ARG),
                    onBack = onBack,
                    destinations = RepaymentDraftDestinations(runtime.navController::openExpense, shellState::openCreditAccount,
                        { id -> shellState.openSecondaryPage(ProductSecondaryPage.Funds,
                            ProductSecondaryPage.Funds.route + "?capture=" + android.net.Uri.encode(id)) }),
                )
            }
        }
    }
}

private fun NavGraphBuilder.addObligationSyncRoute(dependencies: MainProductRouteDependencies) {
    with(dependencies) {
        composable(ProductSecondaryPage.ObligationSync.route) {
            val vm: OutboxStatusViewModel = viewModel(
                factory = outboxStatusViewModelFactory(
                    screenFactory.outboxRepository, screenFactory.repository,
                    com.ticketbox.viewmodel.OutboxRecoveryRepositories(screenFactory.debtCreationRepository,
                        screenFactory.recurringRepository.occurrences, screenFactory.incomePlanRepository,
                        screenFactory.debtWriteRepository, screenFactory.goalEditRepository, screenFactory.budgetRepository, screenFactory.recurringRepository, screenFactory.ruleRepository, repaymentReviews = screenFactory.repaymentReviewRepository),
                ),
            )
            SyncStatusScreen(viewModel = vm, onBack = onBack,
                navigation = com.ticketbox.ui.screens.settings.SyncStatusNavigation(
                    onOpenFunds = { shellState.openSecondaryPage(ProductSecondaryPage.Funds) },
                    onOpenExpense = runtime.navController::openExpense,
                    onOpenInbox = { shellState.openPrimaryDomainRoot(PrimaryDomain.Inbox) },
                    onOpenBudget = { month -> navController.navigate(budgetRoute(month)) },
                    onOpenArrangement = { month -> navController.navigate(monthlyArrangementRoute(month)) },
                    onOpenGoalCreation = { original -> navController.navigate(goalCreationRoute(original)) },
                    onOpenGoalEdit = { original -> navController.navigate(goalEditRoute(original.row.targetId.removePrefix("goal:"), original.row.type)) },
                    onOpenRuleSubmission = { id -> navController.navigate(categoryRuleSubmissionRoute(id)) },
                    onOpenIncomeSubmission = { id -> navController.navigate(incomePlanSubmissionRoute(id)) },
                    onOpenRateSubmission = { id -> navController.navigate(budgetAdviceSubmissionRoute(id)) },
                    onRepairCorrectionRate = { binding, gap -> navController.navigate(correctionRateRoute(binding, gap)) },
                    onOpenRecurring = { shellState.openSecondaryPage(ProductSecondaryPage.Recurring) },
                ))
        }
    }
}

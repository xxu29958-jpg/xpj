package com.ticketbox.ui.navigation

import android.annotation.SuppressLint
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.AnimatedContentTransitionScope
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.animation.togetherWith
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.navArgument
import com.ticketbox.ui.components.AppBottomNav
import com.ticketbox.ui.components.DrillTransition
import com.ticketbox.ui.design.AppMotion

internal data class MainNavigationRuntime(
    val navController: NavHostController,
    val shellState: MainShellState,
    val screenFactory: MainScreenFactory,
)

@Composable
internal fun MainNavGraph(
    runtime: MainNavigationRuntime,
    snackbarHostState: SnackbarHostState,
    preferenceControls: SettingsPreferenceControls,
    onBindingCleared: () -> Unit,
) {
    NavHost(
        navController = runtime.navController,
        startDestination = MAIN_ROUTE,
        modifier = Modifier.fillMaxSize(),
    ) {
        composable(MAIN_ROUTE) {
            MainRoute(
                runtime = runtime,
                snackbarHostState = snackbarHostState,
                preferenceControls = preferenceControls,
                onBindingCleared = onBindingCleared,
            )
        }
        composable(
            route = EXPENSE_ROUTE,
            arguments = listOf(navArgument(EXPENSE_ID_ARG) { type = NavType.LongType }),
            enterTransition = { expenseEditEnter() },
            exitTransition = { expenseEditExit() },
            popEnterTransition = { expenseEditEnter() },
            popExitTransition = { expenseEditExit() },
        ) { backStackEntry ->
            val expenseId = backStackEntry.arguments?.getLong(EXPENSE_ID_ARG) ?: return@composable
            ExpenseEditRoute(
                expenseId = expenseId,
                screenFactory = runtime.screenFactory,
                onBack = { runtime.navController.popBackStack() },
                onCompleted = {
                    runtime.shellState.markExpenseEditCompleted()
                    runtime.navController.popBackStack()
                },
                onOpenRepaymentDrafts = { draftPublicId ->
                    runtime.shellState.openRepaymentDrafts(draftPublicId)
                    runtime.navController.popBackStack()
                },
            )
        }
    }
}

@Composable
@SuppressLint("UnusedMaterial3ScaffoldPaddingParameter")
private fun MainRoute(
    runtime: MainNavigationRuntime,
    snackbarHostState: SnackbarHostState,
    preferenceControls: SettingsPreferenceControls,
    onBindingCleared: () -> Unit,
) {
    val shellState = runtime.shellState
    Scaffold(
        containerColor = Color.Transparent,
        contentWindowInsets = WindowInsets(0.dp),
        snackbarHost = { SnackbarHost(snackbarHostState) },
        bottomBar = {
            if (shellState.statsSecondaryPage == null && !shellState.settingsSecondaryActive) {
                AppBottomNav(
                    items = BottomTab.entries.map { it.toBottomNavItem() },
                    selectedKey = shellState.selectedTab.key,
                    onSelect = { item -> shellState.selectBottomTab(item.key) },
                )
            }
        },
    ) { _ ->
        Box(modifier = Modifier.fillMaxSize()) {
            MainRouteContent(
                runtime = runtime,
                preferenceControls = preferenceControls,
                onBindingCleared = onBindingCleared,
            )
        }
    }
}

@Composable
private fun MainRouteContent(
    runtime: MainNavigationRuntime,
    preferenceControls: SettingsPreferenceControls,
    onBindingCleared: () -> Unit,
) {
    val shellState = runtime.shellState
    val screenFactory = runtime.screenFactory
    DrillTransition(targetState = shellState.statsSecondaryPage, label = "stats-secondary") { page ->
        when (page) {
            StatsSecondaryPage.SpendingGoal -> CreateSpendingGoalRoute(
                screenFactory = screenFactory,
                onBack = shellState::closeStatsSecondaryPage,
                onCreated = {
                    shellState.markDashboardCardsChanged()
                    shellState.closeStatsSecondaryPage()
                },
            )

            StatsSecondaryPage.Budget -> BudgetRoute(
                screenFactory = screenFactory,
                onBack = shellState::closeStatsSecondaryPage,
            )

            StatsSecondaryPage.Recurring -> RecurringRoute(
                screenFactory = screenFactory,
                onBack = shellState::closeStatsSecondaryPage,
            )

            StatsSecondaryPage.IncomePlans -> IncomePlanRoute(
                screenFactory = screenFactory,
                onBack = shellState::closeStatsSecondaryPage,
            )

            StatsSecondaryPage.BillSplits -> BillSplitRoute(
                screenFactory = screenFactory,
                onBack = shellState::closeStatsSecondaryPage,
            )

            StatsSecondaryPage.GlobalSearch -> SearchRoute(
                navController = runtime.navController,
                screenFactory = screenFactory,
                onBack = shellState::closeStatsSecondaryPage,
            )

            StatsSecondaryPage.DebtGoals -> DebtGoalRoute(
                screenFactory = screenFactory,
                onBack = shellState::closeStatsSecondaryPage,
            )

            StatsSecondaryPage.Debts -> DebtRoute(
                screenFactory = screenFactory,
                onBack = shellState::closeStatsSecondaryPage,
            )

            StatsSecondaryPage.Receivables -> ReceivablesRoute(
                screenFactory = screenFactory,
                onBack = shellState::closeStatsSecondaryPage,
            )

            StatsSecondaryPage.RepaymentDrafts -> RepaymentDraftRoute(
                screenFactory = screenFactory,
                focusedDraftPublicId = shellState.focusedRepaymentDraftPublicId,
                onFocusConsumed = shellState::clearFocusedRepaymentDraft,
                onBack = shellState::closeStatsSecondaryPage,
            )

            null -> MainTabRoute(
                runtime = runtime,
                preferenceControls = preferenceControls,
                onBindingCleared = onBindingCleared,
            )
        }
    }
}

@Composable
private fun MainTabRoute(
    runtime: MainNavigationRuntime,
    preferenceControls: SettingsPreferenceControls,
    onBindingCleared: () -> Unit,
) {
    val shellState = runtime.shellState
    val screenFactory = runtime.screenFactory
    AnimatedContent(
        targetState = shellState.selectedTab,
        transitionSpec = {
            fadeIn(AppMotion.standardSpec(AppMotion.normalMillis))
                .togetherWith(fadeOut(AppMotion.exitSpec(AppMotion.fastMillis)))
        },
        label = "main-tab",
    ) { tab ->
        when (tab) {
            BottomTab.Today -> TodayRoute(
                shellState = shellState,
                screenFactory = screenFactory,
            )

            BottomTab.Pending -> PendingRoute(
                navController = runtime.navController,
                shellState = shellState,
                screenFactory = screenFactory,
            )

            BottomTab.Ledger -> LedgerRoute(
                navController = runtime.navController,
                shellState = shellState,
                screenFactory = screenFactory,
            )

            BottomTab.Insights -> StatsRoute(
                shellState = shellState,
                screenFactory = screenFactory,
            )

            BottomTab.Settings -> SettingsRoute(
                shellState = shellState,
                screenFactory = screenFactory,
                preferenceControls = preferenceControls,
                onBindingCleared = onBindingCleared,
            )
        }
    }
}

private fun AnimatedContentTransitionScope<NavBackStackEntry>.expenseEditEnter(): EnterTransition =
    fadeIn(AppMotion.standardSpec(AppMotion.normalMillis)) +
        slideInVertically(AppMotion.emphasizedSpec(AppMotion.normalMillis)) { fullHeight ->
            (fullHeight * EXPENSE_EDIT_SLIDE_FRACTION).toInt()
        }

private fun AnimatedContentTransitionScope<NavBackStackEntry>.expenseEditExit(): ExitTransition =
    fadeOut(AppMotion.exitSpec(AppMotion.fastMillis)) +
        slideOutVertically(AppMotion.exitSpec(AppMotion.fastMillis)) { fullHeight ->
            (fullHeight * EXPENSE_EDIT_SLIDE_FRACTION).toInt()
        }

private const val EXPENSE_EDIT_SLIDE_FRACTION = 0.04f

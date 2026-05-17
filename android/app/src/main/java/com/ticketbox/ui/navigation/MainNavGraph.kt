package com.ticketbox.ui.navigation

import android.annotation.SuppressLint
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
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.navArgument
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.components.AppBottomNav

@Composable
internal fun MainNavGraph(
    navController: NavHostController,
    shellState: MainShellState,
    screenFactory: MainScreenFactory,
    currentSkin: AppSkin,
    snackbarHostState: SnackbarHostState,
    onSkinChange: (AppSkin) -> Unit,
    onBindingCleared: () -> Unit,
) {
    NavHost(
        navController = navController,
        startDestination = MAIN_ROUTE,
        modifier = Modifier.fillMaxSize(),
    ) {
        composable(MAIN_ROUTE) {
            MainRoute(
                navController = navController,
                shellState = shellState,
                screenFactory = screenFactory,
                currentSkin = currentSkin,
                snackbarHostState = snackbarHostState,
                onSkinChange = onSkinChange,
                onBindingCleared = onBindingCleared,
            )
        }
        composable(
            route = EXPENSE_ROUTE,
            arguments = listOf(navArgument(EXPENSE_ID_ARG) { type = NavType.LongType }),
        ) { backStackEntry ->
            val expenseId = backStackEntry.arguments?.getLong(EXPENSE_ID_ARG) ?: return@composable
            ExpenseEditRoute(
                expenseId = expenseId,
                screenFactory = screenFactory,
                onBack = { navController.popBackStack() },
                onCompleted = {
                    shellState.markExpenseEditCompleted()
                    navController.popBackStack()
                },
            )
        }
    }
}

@Composable
@SuppressLint("UnusedMaterial3ScaffoldPaddingParameter")
private fun MainRoute(
    navController: NavHostController,
    shellState: MainShellState,
    screenFactory: MainScreenFactory,
    currentSkin: AppSkin,
    snackbarHostState: SnackbarHostState,
    onSkinChange: (AppSkin) -> Unit,
    onBindingCleared: () -> Unit,
) {
    Scaffold(
        containerColor = Color.Transparent,
        contentWindowInsets = WindowInsets(0.dp),
        snackbarHost = { SnackbarHost(snackbarHostState) },
        bottomBar = {
            if (shellState.statsSecondaryPage == null) {
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
                navController = navController,
                shellState = shellState,
                screenFactory = screenFactory,
                currentSkin = currentSkin,
                onSkinChange = onSkinChange,
                onBindingCleared = onBindingCleared,
            )
        }
    }
}

@Composable
private fun MainRouteContent(
    navController: NavHostController,
    shellState: MainShellState,
    screenFactory: MainScreenFactory,
    currentSkin: AppSkin,
    onSkinChange: (AppSkin) -> Unit,
    onBindingCleared: () -> Unit,
) {
    when (shellState.statsSecondaryPage) {
        StatsSecondaryPage.Budget -> BudgetRoute(
            screenFactory = screenFactory,
            onBack = shellState::closeStatsSecondaryPage,
        )

        StatsSecondaryPage.Recurring -> RecurringRoute(
            screenFactory = screenFactory,
            onBack = shellState::closeStatsSecondaryPage,
        )

        null -> MainTabRoute(
            navController = navController,
            shellState = shellState,
            screenFactory = screenFactory,
            currentSkin = currentSkin,
            onSkinChange = onSkinChange,
            onBindingCleared = onBindingCleared,
        )
    }
}

@Composable
private fun MainTabRoute(
    navController: NavHostController,
    shellState: MainShellState,
    screenFactory: MainScreenFactory,
    currentSkin: AppSkin,
    onSkinChange: (AppSkin) -> Unit,
    onBindingCleared: () -> Unit,
) {
    when (shellState.selectedTab) {
        BottomTab.Pending -> PendingRoute(
            navController = navController,
            shellState = shellState,
            screenFactory = screenFactory,
        )

        BottomTab.Ledger -> LedgerRoute(
            navController = navController,
            shellState = shellState,
            screenFactory = screenFactory,
        )

        BottomTab.Search -> SearchRoute(
            navController = navController,
            screenFactory = screenFactory,
        )

        BottomTab.Stats -> StatsRoute(
            shellState = shellState,
            screenFactory = screenFactory,
        )

        BottomTab.Settings -> SettingsRoute(
            shellState = shellState,
            screenFactory = screenFactory,
            currentSkin = currentSkin,
            onSkinChange = onSkinChange,
            onBindingCleared = onBindingCleared,
        )
    }
}

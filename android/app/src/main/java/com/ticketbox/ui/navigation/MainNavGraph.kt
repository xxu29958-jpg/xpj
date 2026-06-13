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
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.components.AppBottomNav
import com.ticketbox.ui.components.DrillTransition
import com.ticketbox.ui.design.AppMotion

@Composable
internal fun MainNavGraph(
    navController: NavHostController,
    shellState: MainShellState,
    screenFactory: MainScreenFactory,
    currentSkin: AppSkin,
    currentCurrency: CurrencyCode,
    snackbarHostState: SnackbarHostState,
    onSkinChange: (AppSkin) -> Unit,
    onCurrencyChange: (CurrencyCode) -> Unit,
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
                currentCurrency = currentCurrency,
                snackbarHostState = snackbarHostState,
                onSkinChange = onSkinChange,
                onCurrencyChange = onCurrencyChange,
                onBindingCleared = onBindingCleared,
            )
        }
        composable(
            route = EXPENSE_ROUTE,
            arguments = listOf(navArgument(EXPENSE_ID_ARG) { type = NavType.LongType }),
            // 主页 → 编辑页：淡入 + 轻微上移，给一个「推入」的层级感（pop 时反向）。
            enterTransition = { expenseEditEnter() },
            exitTransition = { expenseEditExit() },
            popEnterTransition = { expenseEditEnter() },
            popExitTransition = { expenseEditExit() },
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
    currentCurrency: CurrencyCode,
    snackbarHostState: SnackbarHostState,
    onSkinChange: (AppSkin) -> Unit,
    onCurrencyChange: (CurrencyCode) -> Unit,
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
                currentCurrency = currentCurrency,
                onSkinChange = onSkinChange,
                onCurrencyChange = onCurrencyChange,
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
    currentCurrency: CurrencyCode,
    onSkinChange: (AppSkin) -> Unit,
    onCurrencyChange: (CurrencyCode) -> Unit,
    onBindingCleared: () -> Unit,
) {
    // Reports → 二级页（预算 / 周期）钻取：进出有方向感，返回时反向收起。
    DrillTransition(targetState = shellState.statsSecondaryPage, label = "stats-secondary") { page ->
        when (page) {
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

            // A3 IA: 账本动作区「拆账中心」入口 → 全屏二级页(返回回到账本)。
            StatsSecondaryPage.BillSplits -> BillSplitRoute(
                screenFactory = screenFactory,
                onBack = shellState::closeStatsSecondaryPage,
            )

            null -> MainTabRoute(
                navController = navController,
                shellState = shellState,
                screenFactory = screenFactory,
                currentSkin = currentSkin,
                currentCurrency = currentCurrency,
                onSkinChange = onSkinChange,
                onCurrencyChange = onCurrencyChange,
                onBindingCleared = onBindingCleared,
            )
        }
    }
}

@Composable
private fun MainTabRoute(
    navController: NavHostController,
    shellState: MainShellState,
    screenFactory: MainScreenFactory,
    currentSkin: AppSkin,
    currentCurrency: CurrencyCode,
    onSkinChange: (AppSkin) -> Unit,
    onCurrencyChange: (CurrencyCode) -> Unit,
    onBindingCleared: () -> Unit,
) {
    // 底栏 tab 切换：交叉淡入淡出（与 SkeletonScaffold 同形，纯 AppMotion，无新数值），
    // 不再瞬跳。过场中（~220ms）新旧两个 tab 组合短暂共存，结束即销毁旧组合；
    // 静止态仍然只有一个 tab 组合存活（与原 when 一致）。
    AnimatedContent(
        targetState = shellState.selectedTab,
        transitionSpec = {
            fadeIn(AppMotion.standardSpec(AppMotion.normalMillis))
                .togetherWith(fadeOut(AppMotion.exitSpec(AppMotion.fastMillis)))
        },
        label = "main-tab",
    ) { tab ->
        when (tab) {
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

            BottomTab.Reports -> StatsRoute(
                shellState = shellState,
                screenFactory = screenFactory,
            )

            BottomTab.Search -> SearchRoute(
                navController = navController,
                screenFactory = screenFactory,
            )

            BottomTab.Settings -> SettingsRoute(
                shellState = shellState,
                screenFactory = screenFactory,
                currentSkin = currentSkin,
                currentCurrency = currentCurrency,
                onSkinChange = onSkinChange,
                onCurrencyChange = onCurrencyChange,
                onBindingCleared = onBindingCleared,
            )
        }
    }
}

/**
 * 编辑页进入：淡入 + 从下方 4% 高度上移落位（量级与 [DrillTransition] 的 scale 0.04 一致，
 * 跨屏过场保持同一节奏）。时长/缓动全取 [AppMotion]，无内联数值。
 *
 * 「减动效」：这些 spec 都基于 `tween`，Compose 经帧时钟的 CoroutineContext
 * （`MotionDurationScale` 元素，AndroidUiDispatcher 注入）乘上系统「动画时长
 * 缩放」（开发者选项 / 无障碍「移除动画」）。
 * 系统关闭动画时该缩放为 0，过场即时完成——本项目未自定义 `MotionDurationScale`，
 * 故无需在此手动接系统开关。应用内「减少动效」开关只管沉浸式背景（见 ImmersiveBackground），
 * 不接屏级过场（量级仅 220ms 淡入，留观察；要纳入须另立设计决策）。
 */
private fun AnimatedContentTransitionScope<NavBackStackEntry>.expenseEditEnter(): EnterTransition =
    fadeIn(AppMotion.standardSpec(AppMotion.normalMillis)) +
        slideInVertically(AppMotion.emphasizedSpec(AppMotion.normalMillis)) { fullHeight ->
            (fullHeight * EXPENSE_EDIT_SLIDE_FRACTION).toInt()
        }

/** 编辑页退出：淡出 + 向下 4% 轻移，与 [expenseEditEnter] 反向（加速退场曲线）。 */
private fun AnimatedContentTransitionScope<NavBackStackEntry>.expenseEditExit(): ExitTransition =
    fadeOut(AppMotion.exitSpec(AppMotion.fastMillis)) +
        slideOutVertically(AppMotion.exitSpec(AppMotion.fastMillis)) { fullHeight ->
            (fullHeight * EXPENSE_EDIT_SLIDE_FRACTION).toInt()
        }

/** 编辑页推入/退出的位移幅度（容器高度占比）；与 [DrillTransition] 的 scale 0.04 同量级。 */
private const val EXPENSE_EDIT_SLIDE_FRACTION = 0.04f

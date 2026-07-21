package com.ticketbox.ui.navigation

import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController

/**
 * 一级域的三种产品意图不可合并：
 * 普通切换恢复各域现场；重选当前域回根；带筛选/上传等一次性动作的定向入口必须直达根。
 */
internal enum class PrimaryDomainSelectionBehavior {
    SwitchBackStack,
    ReturnToRoot,
    OpenRoot,
}

internal sealed interface PrimaryDomainNavigationStrategy {
    data class SwitchBackStack(
        val route: String,
        val launchSingleTop: Boolean = true,
        val savePoppedState: Boolean = true,
        val restoreSavedState: Boolean = true,
    ) : PrimaryDomainNavigationStrategy

    data class ReturnToRoot(
        val route: String,
    ) : PrimaryDomainNavigationStrategy

    data class OpenRoot(
        val route: String,
        val launchSingleTop: Boolean = true,
        val savePoppedState: Boolean = true,
        val restoreSavedState: Boolean = false,
    ) : PrimaryDomainNavigationStrategy
}

internal val ProductSecondaryPage.primaryDomain: PrimaryDomain
    get() = PrimaryDomain.entries.first { domain ->
        route.startsWith("${domain.route}/")
    }

internal val MainProductDestination.primaryDomain: PrimaryDomain?
    get() = when (this) {
        is MainProductDestination.Domain -> domain
        is MainProductDestination.Secondary -> page.primaryDomain
        MainProductDestination.Workspace -> null
    }

internal fun MainNavigationRequest.OpenDomain.navigationStrategy(
    currentDestination: MainProductDestination?,
): PrimaryDomainNavigationStrategy =
    when {
        selectionBehavior != PrimaryDomainSelectionBehavior.SwitchBackStack &&
            currentDestination?.primaryDomain == domain ->
            PrimaryDomainNavigationStrategy.ReturnToRoot(route = domain.route)
        selectionBehavior == PrimaryDomainSelectionBehavior.OpenRoot ->
            PrimaryDomainNavigationStrategy.OpenRoot(route = domain.route)
        else -> PrimaryDomainNavigationStrategy.SwitchBackStack(route = domain.route)
    }

internal fun NavHostController.navigatePrimaryDomain(
    strategy: PrimaryDomainNavigationStrategy,
) {
    when (strategy) {
        is PrimaryDomainNavigationStrategy.SwitchBackStack -> {
            navigate(strategy.route) {
                popUpTo(graph.findStartDestination().id) {
                    saveState = strategy.savePoppedState
                }
                launchSingleTop = strategy.launchSingleTop
                restoreState = strategy.restoreSavedState
            }
        }
        is PrimaryDomainNavigationStrategy.ReturnToRoot -> {
            popBackStack(strategy.route, inclusive = false)
        }
        is PrimaryDomainNavigationStrategy.OpenRoot -> {
            clearBackStack(strategy.route)
            navigate(strategy.route) {
                popUpTo(graph.findStartDestination().id) {
                    saveState = strategy.savePoppedState
                }
                launchSingleTop = strategy.launchSingleTop
                restoreState = strategy.restoreSavedState
            }
        }
    }
}

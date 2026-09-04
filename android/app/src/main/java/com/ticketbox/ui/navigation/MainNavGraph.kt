package com.ticketbox.ui.navigation

import androidx.compose.animation.AnimatedContentTransitionScope
import androidx.compose.animation.EnterTransition
import androidx.compose.animation.ExitTransition
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.adaptive.currentWindowAdaptiveInfo
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.Alignment
import androidx.compose.ui.res.stringResource
import androidx.navigation.NavBackStackEntry
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.ticketbox.ui.components.AppBottomNav
import com.ticketbox.ui.components.AppAccountButton
import com.ticketbox.ui.components.AppNavigationRail
import com.ticketbox.ui.components.AppPostureSafeContent
import com.ticketbox.ui.components.AppPrimaryNavItem
import com.ticketbox.ui.components.LocalAppAdaptivePaneDirective
import com.ticketbox.ui.components.LocalPrimaryNavigationInsetHandled
import com.ticketbox.ui.components.LocalPrimaryStatusInsetHandled
import com.ticketbox.ui.design.AppAdaptiveLayoutPolicy
import com.ticketbox.ui.design.AppAlpha
import com.ticketbox.ui.design.AppMotion
import com.ticketbox.ui.design.AppPrimaryNavigationMode
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.AppTextHierarchy
import com.ticketbox.ui.design.LocalAppAdaptiveLayoutPolicy
import com.ticketbox.ui.design.toAppAdaptiveLayoutPolicy
import com.ticketbox.ui.design.toAppAdaptivePaneDirective
import com.ticketbox.ui.design.toAppPostureSafeHingeBounds

internal data class MainNavigationRuntime(
    val navController: NavHostController,
    val shellState: MainShellState,
    val screenFactory: MainScreenFactory,
)

internal data class MainWorkspaceControls(
    val preferences: SettingsPreferenceControls,
    val onBindingCleared: () -> Unit,
)

private data class MainProductShellLayout(
    val showPrimaryNavigation: Boolean,
    val activeDomain: PrimaryDomain?,
    val useNavigationRail: Boolean,
    val outerBottomBarHandlesInsets: Boolean,
    val primaryNavigationItems: List<AppPrimaryNavItem>,
    val adaptiveLayoutPolicy: AppAdaptiveLayoutPolicy,
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
                onCompleted = { adviceInputsChanged ->
                    runtime.shellState.markExpenseEditCompleted()
                    // Narrow hook (218-B4 review P2-19): only edits that moved
                    // advisor-payload fields (amount / currency / category /
                    // date-time, or confirmed-set membership) invalidate the
                    // advice cache — note/tag/merchant-only edits preserve it.
                    if (adviceInputsChanged) {
                        runtime.screenFactory.budgetRepository.invalidateBudgetAdvice()
                    }
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
private fun MainRoute(
    runtime: MainNavigationRuntime,
    snackbarHostState: SnackbarHostState,
    preferenceControls: SettingsPreferenceControls,
    onBindingCleared: () -> Unit,
) {
    val shellState = runtime.shellState
    val productNavController = rememberNavController()
    val productBackStackEntry by productNavController.currentBackStackEntryAsState()
    val productDestination = mainProductDestination(productBackStackEntry?.destination?.route)
        ?: MainProductDestination.Domain(PrimaryDomain.Inbox)
    val windowAdaptiveInfo = currentWindowAdaptiveInfo(
        supportLargeAndXLargeWidth = true,
    )
    val adaptiveLayoutPolicy = windowAdaptiveInfo.toAppAdaptiveLayoutPolicy()
    val adaptivePaneDirective = windowAdaptiveInfo.toAppAdaptivePaneDirective(adaptiveLayoutPolicy)
    val postureSafeHingeBounds = windowAdaptiveInfo.toAppPostureSafeHingeBounds(
        adaptiveLayoutPolicy,
    )
    val showPrimaryNavigation = productDestination is MainProductDestination.Domain
    val useNavigationRail = showPrimaryNavigation &&
        adaptiveLayoutPolicy.primaryNavigation == AppPrimaryNavigationMode.Rail
    val outerBottomBarHandlesInsets = showPrimaryNavigation && !useNavigationRail
    val shellLayout = MainProductShellLayout(
        showPrimaryNavigation = showPrimaryNavigation,
        activeDomain = (productDestination as? MainProductDestination.Domain)?.domain,
        useNavigationRail = useNavigationRail,
        outerBottomBarHandlesInsets = outerBottomBarHandlesInsets,
        primaryNavigationItems = PrimaryDomain.entries.map { it.toPrimaryNavItem() },
        adaptiveLayoutPolicy = adaptiveLayoutPolicy,
    )
    val workspaceControls = MainWorkspaceControls(
        preferences = preferenceControls,
        onBindingCleared = onBindingCleared,
    )

    MainProductNavigationSync(
        navController = productNavController,
        shellState = shellState,
        currentRoute = productBackStackEntry?.destination?.route,
    )

    CompositionLocalProvider(LocalAppAdaptivePaneDirective provides adaptivePaneDirective) {
        AppPostureSafeContent(excludedBounds = postureSafeHingeBounds) {
            MainProductScaffold(
                runtime = runtime,
                productNavController = productNavController,
                shellLayout = shellLayout,
                snackbarHostState = snackbarHostState,
                workspaceControls = workspaceControls,
            )
        }
    }
}

@Composable
private fun MainProductScaffold(
    runtime: MainNavigationRuntime,
    productNavController: NavHostController,
    shellLayout: MainProductShellLayout,
    snackbarHostState: SnackbarHostState,
    workspaceControls: MainWorkspaceControls,
) {
    Scaffold(
        // The surrounding ImmersiveBackgroundScaffold owns the global backdrop.
        containerColor = androidx.compose.ui.graphics.Color.Transparent,
        contentWindowInsets = WindowInsets(AppSpacing.none),
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            shellLayout.activeDomain?.let { domain ->
                MainDomainTopBar(
                    domain = domain,
                    onOpenWorkspace = runtime.shellState::openAccount,
                )
            }
        },
        bottomBar = {
            if (shellLayout.showPrimaryNavigation && !shellLayout.useNavigationRail) {
                AppBottomNav(
                    items = shellLayout.primaryNavigationItems,
                    selectedKey = runtime.shellState.selectedDomain.key,
                    onSelect = { item -> runtime.shellState.selectPrimaryDomain(item.key) },
                )
            }
        },
    ) { innerPadding ->
        CompositionLocalProvider(
            LocalPrimaryNavigationInsetHandled provides shellLayout.outerBottomBarHandlesInsets,
            LocalPrimaryStatusInsetHandled provides shellLayout.showPrimaryNavigation,
            LocalAppAdaptiveLayoutPolicy provides shellLayout.adaptiveLayoutPolicy,
        ) {
            Row(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(innerPadding),
            ) {
                if (shellLayout.useNavigationRail) {
                    AppNavigationRail(
                        items = shellLayout.primaryNavigationItems,
                        selectedKey = runtime.shellState.selectedDomain.key,
                        onSelect = { item -> runtime.shellState.selectPrimaryDomain(item.key) },
                    )
                }
                Box(
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxHeight(),
                ) {
                    MainProductNavHost(
                        runtime = runtime,
                        navController = productNavController,
                        workspaceControls = workspaceControls,
                    )
                }
            }
        }
    }
}

@Composable
private fun MainDomainTopBar(
    domain: PrimaryDomain,
    onOpenWorkspace: () -> Unit,
) {
    Surface(
        color = MaterialTheme.colorScheme.surface,
        tonalElevation = AppSpacing.none,
        shadowElevation = AppSpacing.none,
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .statusBarsPadding(),
        ) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .heightIn(min = AppSpacing.controlMinHeight)
                    .padding(horizontal = AppSpacing.screenHorizontal),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    text = stringResource(domain.labelRes),
                    modifier = Modifier.weight(1f),
                    color = MaterialTheme.colorScheme.onSurface,
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = AppTextHierarchy.heading.weight,
                )
                AppAccountButton(onClick = onOpenWorkspace)
            }
            HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant.copy(alpha = AppAlpha.soft))
        }
    }
}

@Composable
private fun MainProductNavHost(
    runtime: MainNavigationRuntime,
    navController: NavHostController,
    workspaceControls: MainWorkspaceControls,
) {
    val dependencies = MainProductRouteDependencies(
        runtime = runtime,
        navController = navController,
        workspaceControls = workspaceControls,
    )

    NavHost(
        navController = navController,
        startDestination = PrimaryDomain.Inbox.route,
        modifier = Modifier.fillMaxSize(),
    ) {
        addPrimaryDomainRoutes(dependencies)
        addWorkspaceRoute(dependencies)
        addPlanRoutes(dependencies)
        addInsightsRoutes(dependencies)
        addTransactionRoutes(dependencies)
        addObligationRoutes(dependencies)
    }
}

@Composable
private fun MainProductNavigationSync(
    navController: NavHostController,
    shellState: MainShellState,
    currentRoute: String?,
) {
    LaunchedEffect(currentRoute) {
        mainProductDestination(currentRoute)?.let(shellState::syncDestination)
    }
    LaunchedEffect(shellState.navigationRequest) {
        when (val request = shellState.consumeNavigationRequest()) {
            is MainNavigationRequest.OpenDomain -> {
                navController.navigatePrimaryDomain(
                    request.navigationStrategy(
                        currentDestination = mainProductDestination(currentRoute),
                    ),
                )
            }
            is MainNavigationRequest.OpenSecondary -> {
                navController.navigate(request.route) {
                    launchSingleTop = true
                }
            }
            MainNavigationRequest.OpenWorkspace -> {
                navController.navigate(WORKSPACE_ROUTE) {
                    launchSingleTop = true
                }
            }
            MainNavigationRequest.Back -> {
                navController.popBackStack()
            }
            null -> Unit
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

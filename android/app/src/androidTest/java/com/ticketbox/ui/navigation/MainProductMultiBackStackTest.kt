package com.ticketbox.ui.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.SideEffect
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import org.junit.Assert.assertEquals
import org.junit.Assert.assertSame
import org.junit.Rule
import org.junit.Test

class MainProductMultiBackStackTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun switchingDomainsRestoresDetailViewModelAndReselectingReturnsToRoot() {
        val visibleProbes = mutableMapOf<String, DomainStackProbeViewModel>()
        val navController = setNavigationContent(visibleProbes)
        navigateToDomain(navController, PrimaryDomain.Plans)
        openSecondary(navController, ProductSecondaryPage.Budget)
        val originalPlanProbe = visibleProbes.getValue(ProductSecondaryPage.Budget.route)
        composeRule.runOnIdle {
            originalPlanProbe.filter = "recurring-only"
            originalPlanProbe.scrollIndex = 37
        }

        navigateToDomain(navController, PrimaryDomain.Transactions)
        openSecondary(navController, ProductSecondaryPage.GlobalSearch)
        val originalTransactionsProbe =
            visibleProbes.getValue(ProductSecondaryPage.GlobalSearch.route)
        composeRule.runOnIdle {
            originalTransactionsProbe.filter = "groceries"
            originalTransactionsProbe.scrollIndex = 19
        }

        navigateToDomain(navController, PrimaryDomain.Plans)
        assertCurrentRoute(navController, ProductSecondaryPage.Budget.route)
        assertProbeState(
            visibleProbes,
            ProductSecondaryPage.Budget,
            originalPlanProbe,
            "recurring-only",
            37,
        )

        navigateToDomain(navController, PrimaryDomain.Transactions)
        assertCurrentRoute(navController, ProductSecondaryPage.GlobalSearch.route)
        assertProbeState(
            visibleProbes,
            ProductSecondaryPage.GlobalSearch,
            originalTransactionsProbe,
            "groceries",
            19,
        )

        navigateToDomain(navController, PrimaryDomain.Plans)
        assertCurrentRoute(navController, ProductSecondaryPage.Budget.route)
        openDomainRoot(navController, PrimaryDomain.Transactions)
        assertCurrentRoute(navController, PrimaryDomain.Transactions.route)
        navigateToDomain(navController, PrimaryDomain.Plans)
        assertCurrentRoute(navController, ProductSecondaryPage.Budget.route)
        reselectDomain(navController, PrimaryDomain.Plans)
        assertCurrentRoute(navController, PrimaryDomain.Plans.route)
        navigateToDomain(navController, PrimaryDomain.Transactions)
        assertCurrentRoute(navController, PrimaryDomain.Transactions.route)
    }

    private fun setNavigationContent(
        visibleProbes: MutableMap<String, DomainStackProbeViewModel>,
    ): NavHostController {
        lateinit var navController: NavHostController
        composeRule.setContent {
            navController = rememberNavController()
            NavHost(
                navController = navController,
                startDestination = PrimaryDomain.Inbox.route,
            ) {
                composable(PrimaryDomain.Inbox.route) {}
                composable(PrimaryDomain.Transactions.route) {}
                composable(PrimaryDomain.Plans.route) {}
                composable(ProductSecondaryPage.Budget.route) {
                    captureVisibleProbe(ProductSecondaryPage.Budget, visibleProbes)
                }
                composable(ProductSecondaryPage.GlobalSearch.route) {
                    captureVisibleProbe(ProductSecondaryPage.GlobalSearch, visibleProbes)
                }
            }
        }
        composeRule.waitForIdle()
        return navController
    }

    private fun openSecondary(
        navController: NavHostController,
        page: ProductSecondaryPage,
    ) {
        composeRule.runOnIdle {
            navController.navigate(page.route)
        }
        composeRule.waitForIdle()
    }

    private fun navigateToDomain(
        navController: NavHostController,
        domain: PrimaryDomain,
    ) {
        composeRule.runOnIdle {
            val request = MainNavigationRequest.OpenDomain(domain)
            navController.navigatePrimaryDomain(
                request.navigationStrategy(
                    currentDestination = mainProductDestination(navController.currentDestination?.route),
                ),
            )
        }
        composeRule.waitForIdle()
    }

    private fun openDomainRoot(
        navController: NavHostController,
        domain: PrimaryDomain,
    ) {
        composeRule.runOnIdle {
            val request = MainNavigationRequest.OpenDomain(
                domain = domain,
                selectionBehavior = PrimaryDomainSelectionBehavior.OpenRoot,
            )
            navController.navigatePrimaryDomain(
                request.navigationStrategy(
                    currentDestination = mainProductDestination(navController.currentDestination?.route),
                ),
            )
        }
        composeRule.waitForIdle()
    }

    private fun reselectDomain(
        navController: NavHostController,
        domain: PrimaryDomain,
    ) {
        composeRule.runOnIdle {
            val request = MainNavigationRequest.OpenDomain(
                domain = domain,
                selectionBehavior = PrimaryDomainSelectionBehavior.ReturnToRoot,
            )
            navController.navigatePrimaryDomain(
                request.navigationStrategy(
                    currentDestination = mainProductDestination(navController.currentDestination?.route),
                ),
            )
        }
        composeRule.waitForIdle()
    }

    private fun assertCurrentRoute(
        navController: NavHostController,
        expectedRoute: String,
    ) {
        composeRule.runOnIdle {
            assertEquals(expectedRoute, navController.currentDestination?.route)
        }
    }

    private fun assertProbeState(
        visibleProbes: Map<String, DomainStackProbeViewModel>,
        page: ProductSecondaryPage,
        expectedProbe: DomainStackProbeViewModel,
        expectedFilter: String,
        expectedScrollIndex: Int,
    ) {
        composeRule.runOnIdle {
            val restoredProbe = visibleProbes.getValue(page.route)
            assertSame(expectedProbe, restoredProbe)
            assertEquals(expectedFilter, restoredProbe.filter)
            assertEquals(expectedScrollIndex, restoredProbe.scrollIndex)
        }
    }
}

@Composable
private fun captureVisibleProbe(
    page: ProductSecondaryPage,
    visibleProbes: MutableMap<String, DomainStackProbeViewModel>,
) {
    val probe = viewModel<DomainStackProbeViewModel>()
    SideEffect {
        visibleProbes[page.route] = probe
    }
}

internal class DomainStackProbeViewModel : ViewModel() {
    var filter: String = "all"
    var scrollIndex: Int = 0
}

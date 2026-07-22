package com.ticketbox.ui.navigation

import androidx.compose.foundation.layout.Column
import androidx.compose.material3.Button
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.test.assertHasClickAction
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.screens.pending.NeedsReviewFilter
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.LedgerDataQualityFilter
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Rule
import org.junit.Test

/**
 * Connected contract for the 218-B3 data-quality page: real MainShellState,
 * real NavHostController graph fragment, real DataQualityRoute with its
 * production ViewModel wiring (see [DataQualityConnectedHarness]).
 *
 * The navigation sync replicates MainNavGraph.MainProductNavigationSync
 * (private, not reusable) verbatim; the domain-root probes replicate the
 * consumption halves of PendingRoute / LedgerRoute so the posted one-shot
 * requests are asserted end-to-end, not just at the posting seam.
 */
class DataQualityNavigationContractTest {
    @get:Rule
    val composeRule = createComposeRule()

    private lateinit var navController: NavHostController
    private lateinit var shellState: MainShellState
    private lateinit var probe: NavigationProbe
    private lateinit var apiProbe: DataQualityApiProbe

    @Test
    fun insightsEntryOpensDataQualityPageWithClickableRemediationRows() {
        setContractContent()
        selectDomain(PrimaryDomain.Insights)

        composeRule.onNodeWithText(ENTRY_INSIGHTS).performClick()
        waitForNode(TEXT_MISSING_MERCHANT)

        assertEquals(ProductSecondaryPage.InsightsDataQuality.route, currentRoute())
        assertEquals(PrimaryDomain.Insights, shellState.selectedDomain)
        composeRule.onNodeWithText(TEXT_MISSING_MERCHANT)
            .assertIsDisplayed()
            .assertHasClickAction()
        composeRule.onNodeWithText(TEXT_CONFIRMED_WITHOUT_IMAGE)
            .assertIsDisplayed()
            .assertHasClickAction()
        composeRule.onNodeWithText(TEXT_PAGE_TITLE).assertIsDisplayed()
    }

    @Test
    fun missingMerchantRemediationLandsOnInboxRootAndConsumesFilter() {
        setContractContent()
        openDataQualityFromInsights()

        composeRule.onNodeWithText(TEXT_MISSING_MERCHANT).performClick()
        composeRule.waitForIdle()

        composeRule.runOnIdle {
            assertEquals(PrimaryDomain.Inbox.route, navController.currentDestination?.route)
            assertEquals(PrimaryDomain.Inbox, shellState.selectedDomain)
            assertEquals(NeedsReviewFilter.NeedsMerchant, probe.consumedInboxFilter)
            assertNull("consumed filter must be cleared from the request slot", shellState.pendingFilterRequest.pending)
            // OpenRoot semantics: the domain root is the only surviving entry.
            assertNull(navController.previousBackStackEntry)
        }
    }

    @Test
    fun confirmedWithoutImageRemediationLandsOnTransactionsAndConsumesDrill() {
        setContractContent()
        openDataQualityFromInsights()

        composeRule.onNodeWithText(TEXT_CONFIRMED_WITHOUT_IMAGE).performClick()
        composeRule.waitForIdle()

        composeRule.runOnIdle {
            assertEquals(PrimaryDomain.Transactions.route, navController.currentDestination?.route)
            assertEquals(PrimaryDomain.Transactions, shellState.selectedDomain)
            assertEquals(LedgerDataQualityFilter.ConfirmedWithoutImage, probe.consumedLedgerFilter)
            assertNull("consumed drill must be cleared from the request slot", shellState.ledgerDrill.pending)
        }
    }

    @Test
    fun dataQualityPageSurvivesDomainSwitchRoundTrip() {
        setContractContent()
        openDataQualityFromInsights()
        composeRule.runOnIdle {
            assertEquals(1, apiProbe.dataQualityCallCount)
        }

        selectDomain(PrimaryDomain.Transactions)
        assertEquals(PrimaryDomain.Transactions.route, currentRoute())
        selectDomain(PrimaryDomain.Insights)

        assertEquals(ProductSecondaryPage.InsightsDataQuality.route, currentRoute())
        waitForNode(TEXT_MISSING_MERCHANT)
        composeRule.runOnIdle {
            // Multi-back-stack restore brought the SAME ViewModel back — no reload.
            assertEquals(1, apiProbe.dataQualityCallCount)
        }
        assertEquals(PrimaryDomain.Insights, shellState.selectedDomain)
    }

    @Test
    fun directEntryFromInboxChipWithoutInsightsRootRendersAndRemediates() {
        setContractContent()

        // Cross-domain direct entry (PendingRoute's data-quality chip): no
        // Insights root on the back stack — resolveInsightsViewModelOwner must
        // fall back to the secondary entry instead of crashing.
        composeRule.onNodeWithText(ENTRY_INBOX).performClick()
        waitForNode(TEXT_MISSING_MERCHANT)
        assertEquals(ProductSecondaryPage.InsightsDataQuality.route, currentRoute())
        composeRule.runOnIdle {
            assertThrows(
                "no Insights root on the back stack, yet the page rendered via the fallback owner",
                IllegalArgumentException::class.java,
            ) {
                navController.getBackStackEntry(PrimaryDomain.Insights.route)
            }
        }

        composeRule.onNodeWithText(TEXT_MISSING_MERCHANT).performClick()
        composeRule.waitForIdle()

        composeRule.runOnIdle {
            assertEquals(PrimaryDomain.Inbox.route, navController.currentDestination?.route)
            assertEquals(PrimaryDomain.Inbox, shellState.selectedDomain)
            assertEquals(NeedsReviewFilter.NeedsMerchant, probe.consumedInboxFilter)
        }
    }

    private fun setContractContent() {
        val harness = DataQualityConnectedHarness()
        apiProbe = harness.apiProbe
        probe = NavigationProbe()
        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                shellState = remember { MainShellState() }
                navController = rememberNavController()
                DataQualityContractScaffold(
                    shellState = shellState,
                    navController = navController,
                    screenFactory = harness.screenFactory,
                    probe = probe,
                )
            }
        }
        composeRule.waitForIdle()
    }

    private fun openDataQualityFromInsights() {
        selectDomain(PrimaryDomain.Insights)
        composeRule.onNodeWithText(ENTRY_INSIGHTS).performClick()
        waitForNode(TEXT_MISSING_MERCHANT)
        assertEquals(ProductSecondaryPage.InsightsDataQuality.route, currentRoute())
    }

    private fun selectDomain(domain: PrimaryDomain) {
        composeRule.runOnIdle { shellState.selectPrimaryDomain(domain.key) }
        composeRule.waitForIdle()
    }

    private fun currentRoute(): String? {
        var route: String? = null
        composeRule.runOnIdle { route = navController.currentDestination?.route }
        return route
    }

    private fun waitForNode(text: String) {
        composeRule.waitUntil(timeoutMillis = 10_000) {
            composeRule.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty()
        }
    }

    private companion object {
        const val ENTRY_INSIGHTS = "dq-entry-insights"
        const val ENTRY_INBOX = "dq-entry-inbox"
        const val TEXT_PAGE_TITLE = "数据质量"
        const val TEXT_MISSING_MERCHANT = "缺商家"
        const val TEXT_CONFIRMED_WITHOUT_IMAGE = "已确认无图"
    }
}

private class NavigationProbe {
    var consumedInboxFilter: NeedsReviewFilter? = null
    var consumedLedgerFilter: LedgerDataQualityFilter? = null
}

@Composable
private fun DataQualityContractScaffold(
    shellState: MainShellState,
    navController: NavHostController,
    screenFactory: MainScreenFactory,
    probe: NavigationProbe,
) {
    val backStackEntry by navController.currentBackStackEntryAsState()
    ContractNavigationSync(
        navController = navController,
        shellState = shellState,
        currentRoute = backStackEntry?.destination?.route,
    )
    NavHost(
        navController = navController,
        startDestination = PrimaryDomain.Inbox.route,
    ) {
        composable(PrimaryDomain.Inbox.route) { InboxRootProbe(shellState, probe) }
        composable(PrimaryDomain.Transactions.route) { TransactionsRootProbe(shellState, probe) }
        composable(PrimaryDomain.Insights.route) { InsightsRootProbe(shellState) }
        composable(ProductSecondaryPage.InsightsDataQuality.route) { entry ->
            DataQualityRoute(
                navController = navController,
                currentEntry = entry,
                screenFactory = screenFactory,
                shellState = shellState,
                onBack = { navController.popBackStack() },
            )
        }
    }
}

/** Verbatim replica of MainNavGraph.MainProductNavigationSync (private there). */
@Composable
private fun ContractNavigationSync(
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

@Composable
private fun InboxRootProbe(shellState: MainShellState, probe: NavigationProbe) {
    // Consumption shape mirrors PendingRoute (requestedFilter + consume-on-apply).
    LaunchedEffect(shellState.pendingFilterRequest.pending) {
        shellState.pendingFilterRequest.consume()?.let { probe.consumedInboxFilter = it }
    }
    Column {
        Text("inbox-root")
        Button(
            onClick = { shellState.openSecondaryPage(ProductSecondaryPage.InsightsDataQuality) },
        ) {
            Text("dq-entry-inbox")
        }
    }
}

@Composable
private fun TransactionsRootProbe(shellState: MainShellState, probe: NavigationProbe) {
    // Consumption shape mirrors LedgerRoute.ApplyPendingLedgerDrill.
    LaunchedEffect(shellState.ledgerDrill.pending) {
        when (val request = shellState.ledgerDrill.consume()) {
            is LedgerDrillRequest.DataQuality -> probe.consumedLedgerFilter = request.filter
            else -> Unit
        }
    }
    Text("transactions-root")
}

@Composable
private fun InsightsRootProbe(shellState: MainShellState) {
    Column {
        Text("insights-root")
        Button(
            onClick = { shellState.openSecondaryPage(ProductSecondaryPage.InsightsDataQuality) },
        ) {
            Text("dq-entry-insights")
        }
    }
}

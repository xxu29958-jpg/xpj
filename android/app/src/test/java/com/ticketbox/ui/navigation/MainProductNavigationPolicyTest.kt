package com.ticketbox.ui.navigation

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertIs
import kotlin.test.assertTrue

class MainProductNavigationPolicyTest {
    @Test
    fun strategyPreservesEachDomainStackButReselectingItsDetailReturnsToRoot() {
        PrimaryDomain.entries.forEach { domain ->
            val currentDomain =
                if (domain == PrimaryDomain.Inbox) PrimaryDomain.Transactions else PrimaryDomain.Inbox
            val strategy = MainNavigationRequest.OpenDomain(domain).navigationStrategy(
                currentDestination = MainProductDestination.Domain(currentDomain),
            )
            val switch = assertIs<PrimaryDomainNavigationStrategy.SwitchBackStack>(strategy)

            assertEquals(domain.route, switch.route)
            assertTrue(switch.launchSingleTop)
            assertTrue(switch.savePoppedState)
            assertTrue(switch.restoreSavedState)
        }

        val returnToPlansRoot = MainNavigationRequest.OpenDomain(
            domain = PrimaryDomain.Plans,
            selectionBehavior = PrimaryDomainSelectionBehavior.ReturnToRoot,
        ).navigationStrategy(
            currentDestination = MainProductDestination.Secondary(ProductSecondaryPage.Budget),
        )
        assertEquals(
            PrimaryDomainNavigationStrategy.ReturnToRoot(PrimaryDomain.Plans.route),
            returnToPlansRoot,
        )

        val racedReselect = MainNavigationRequest.OpenDomain(
            domain = PrimaryDomain.Plans,
            selectionBehavior = PrimaryDomainSelectionBehavior.ReturnToRoot,
        ).navigationStrategy(
            currentDestination = MainProductDestination.Domain(PrimaryDomain.Inbox),
        )
        assertIs<PrimaryDomainNavigationStrategy.SwitchBackStack>(racedReselect)

        val directedRoot = MainNavigationRequest.OpenDomain(
            domain = PrimaryDomain.Transactions,
            selectionBehavior = PrimaryDomainSelectionBehavior.OpenRoot,
        ).navigationStrategy(
            currentDestination = MainProductDestination.Secondary(ProductSecondaryPage.Budget),
        )
        val openRoot = assertIs<PrimaryDomainNavigationStrategy.OpenRoot>(directedRoot)
        assertTrue(openRoot.launchSingleTop)
        assertTrue(openRoot.savePoppedState)
        assertFalse(openRoot.restoreSavedState)

        val secondaryOwners = ProductSecondaryPage.entries.associateWith(
            ProductSecondaryPage::primaryDomain,
        )
        assertEquals(PrimaryDomain.Inbox, secondaryOwners.getValue(ProductSecondaryPage.InboxProcessing))
        assertEquals(PrimaryDomain.Transactions, secondaryOwners.getValue(ProductSecondaryPage.GlobalSearch))
        assertEquals(PrimaryDomain.Obligations, secondaryOwners.getValue(ProductSecondaryPage.RepaymentDrafts))
        assertEquals(PrimaryDomain.Plans, secondaryOwners.getValue(ProductSecondaryPage.Budget))
        assertEquals(PrimaryDomain.Insights, secondaryOwners.getValue(ProductSecondaryPage.InsightsDataQuality))
    }
}

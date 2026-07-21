package com.ticketbox.ui.navigation

import com.ticketbox.ui.appearance.background.SurfaceRole
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MainShellStateTest {
    @Test
    fun bottomTabsDescribeFiveProductTaskDomains() {
        assertEquals(
            listOf("inbox", "transactions", "obligations", "plans", "insights"),
            PrimaryDomain.entries.map(PrimaryDomain::key),
        )
        assertEquals(
            listOf(
                "product/inbox",
                "product/transactions",
                "product/obligations",
                "product/plans",
                "product/insights",
            ),
            PrimaryDomain.entries.map(PrimaryDomain::route),
        )
    }

    @Test
    fun inboxAndPlansAreIndependentTopLevelDestinations() {
        val state = MainShellState()

        state.selectPrimaryDomain("inbox")
        assertNull(state.consumeNavigationRequest())
        state.syncDestination(MainProductDestination.Domain(PrimaryDomain.Inbox))
        assertEquals(PrimaryDomain.Inbox, state.selectedDomain)
        assertEquals(SurfaceRole.Pending, state.surfaceRole(currentRoute = MAIN_ROUTE))

        state.selectPrimaryDomain("plans")
        assertEquals(
            MainNavigationRequest.OpenDomain(PrimaryDomain.Plans),
            state.consumeNavigationRequest(),
        )
        state.syncDestination(MainProductDestination.Domain(PrimaryDomain.Plans))
        assertEquals(PrimaryDomain.Plans, state.selectedDomain)
        assertEquals(SurfaceRole.Stats, state.surfaceRole(currentRoute = MAIN_ROUTE))
    }

    @Test
    fun primarySelectionIsNoOpAtItsRootAndReturnsFromItsSecondaryPage() {
        val state = MainShellState()
        state.syncDestination(MainProductDestination.Domain(PrimaryDomain.Plans))

        state.selectPrimaryDomain(PrimaryDomain.Plans.key)

        assertNull(state.consumeNavigationRequest())

        state.openSecondaryPage(ProductSecondaryPage.Budget)
        state.consumeNavigationRequest()
        state.syncDestination(MainProductDestination.Secondary(ProductSecondaryPage.Budget))

        state.selectPrimaryDomain(PrimaryDomain.Plans.key)

        assertEquals(
            MainNavigationRequest.OpenDomain(
                domain = PrimaryDomain.Plans,
                selectionBehavior = PrimaryDomainSelectionBehavior.ReturnToRoot,
            ),
            state.consumeNavigationRequest(),
        )

        val restoredState = MainShellState()
        restoredState.selectPrimaryDomain(PrimaryDomain.Plans.key)
        restoredState.consumeNavigationRequest()
        restoredState.syncDestination(
            MainProductDestination.Secondary(ProductSecondaryPage.Budget),
        )

        restoredState.selectPrimaryDomain(PrimaryDomain.Plans.key)

        assertEquals(
            MainNavigationRequest.OpenDomain(
                domain = PrimaryDomain.Plans,
                selectionBehavior = PrimaryDomainSelectionBehavior.ReturnToRoot,
            ),
            restoredState.consumeNavigationRequest(),
        )

        val processRestoredState = MainShellState()
        processRestoredState.syncDestination(
            MainProductDestination.Secondary(ProductSecondaryPage.Budget),
        )
        assertEquals(PrimaryDomain.Plans, processRestoredState.selectedDomain)
    }

    @Test
    fun selectingTheVisibleRootCancelsASupersededDomainRequest() {
        val state = MainShellState()

        state.selectPrimaryDomain(PrimaryDomain.Plans.key)
        state.selectPrimaryDomain(PrimaryDomain.Inbox.key)

        assertEquals(PrimaryDomain.Inbox, state.selectedDomain)
        assertNull(state.consumeNavigationRequest())
    }

    @Test
    fun workspacePreservesLastDomainWhileSecondaryDerivesItsOwningDomain() {
        val state = MainShellState()
        state.selectPrimaryDomain("transactions")
        state.consumeNavigationRequest()
        state.syncDestination(MainProductDestination.Domain(PrimaryDomain.Transactions))

        state.openAccount()
        assertEquals(MainNavigationRequest.OpenWorkspace, state.consumeNavigationRequest())
        state.syncDestination(MainProductDestination.Workspace)
        assertTrue(state.accountOpen)
        assertEquals(SurfaceRole.Settings, state.surfaceRole(currentRoute = MAIN_ROUTE))
        state.closeAccount()
        assertEquals(MainNavigationRequest.Back, state.consumeNavigationRequest())
        state.syncDestination(MainProductDestination.Domain(PrimaryDomain.Transactions))
        assertFalse(state.accountOpen)

        state.openSecondaryPage(ProductSecondaryPage.Budget)
        assertEquals(
            MainNavigationRequest.OpenSecondary(ProductSecondaryPage.Budget),
            state.consumeNavigationRequest(),
        )
        state.syncDestination(MainProductDestination.Secondary(ProductSecondaryPage.Budget))
        assertEquals(ProductSecondaryPage.Budget, state.secondaryPage)
        assertEquals(PrimaryDomain.Plans, state.selectedDomain)
        state.closeSecondaryPage()
        assertEquals(MainNavigationRequest.Back, state.consumeNavigationRequest())
        state.syncDestination(MainProductDestination.Domain(PrimaryDomain.Transactions))
        assertNull(state.secondaryPage)
    }

    @Test
    fun repaymentReviewIsASecondaryObligationsSurface() {
        val state = MainShellState()
        state.selectPrimaryDomain("obligations")
        state.consumeNavigationRequest()
        state.syncDestination(MainProductDestination.Domain(PrimaryDomain.Obligations))

        state.openRepaymentDrafts()
        assertEquals(
            MainNavigationRequest.OpenSecondary(ProductSecondaryPage.RepaymentDrafts),
            state.consumeNavigationRequest(),
        )
        state.syncDestination(MainProductDestination.Secondary(ProductSecondaryPage.RepaymentDrafts))

        assertEquals(ProductSecondaryPage.RepaymentDrafts, state.secondaryPage)
        assertEquals(PrimaryDomain.Obligations, state.selectedDomain)
        assertEquals(SurfaceRole.Ledger, state.surfaceRole(currentRoute = MAIN_ROUTE))
    }

    @Test
    fun processingIsASecondaryInboxSurfaceWithRealBackStackOwnership() {
        val state = MainShellState()
        state.syncDestination(MainProductDestination.Domain(PrimaryDomain.Inbox))

        state.openSecondaryPage(ProductSecondaryPage.InboxProcessing)
        assertEquals(
            MainNavigationRequest.OpenSecondary(ProductSecondaryPage.InboxProcessing),
            state.consumeNavigationRequest(),
        )
        state.syncDestination(MainProductDestination.Secondary(ProductSecondaryPage.InboxProcessing))

        assertEquals(ProductSecondaryPage.InboxProcessing, state.secondaryPage)
        assertEquals(PrimaryDomain.Inbox, state.selectedDomain)
        assertEquals(SurfaceRole.Pending, state.surfaceRole(currentRoute = MAIN_ROUTE))
        assertEquals(
            MainProductDestination.Secondary(ProductSecondaryPage.InboxProcessing),
            mainProductDestination("product/inbox/processing"),
        )

        state.closeSecondaryPage()
        assertEquals(MainNavigationRequest.Back, state.consumeNavigationRequest())
        state.syncDestination(MainProductDestination.Domain(PrimaryDomain.Inbox))
        assertNull(state.secondaryPage)
    }

    @Test
    fun focusedRepaymentDraftTravelsInTheRestorableNavigationRoute() {
        val state = MainShellState()

        state.openRepaymentDrafts(focusedDraftPublicId = "draft-1")
        assertEquals(
            MainNavigationRequest.OpenSecondary(
                page = ProductSecondaryPage.RepaymentDrafts,
                route = repaymentDraftRoute("draft-1"),
            ),
            state.consumeNavigationRequest(),
        )
        state.syncDestination(MainProductDestination.Secondary(ProductSecondaryPage.RepaymentDrafts))

        state.closeSecondaryPage()
        assertEquals(MainNavigationRequest.Back, state.consumeNavigationRequest())
        state.syncDestination(MainProductDestination.Domain(PrimaryDomain.Obligations))

        assertNull(state.secondaryPage)
    }

    @Test
    fun productRoutesResolveToDomainSecondaryAndWorkspaceDestinations() {
        assertEquals(
            MainProductDestination.Domain(PrimaryDomain.Transactions),
            mainProductDestination(PrimaryDomain.Transactions.route),
        )
        assertEquals(
            MainProductDestination.Secondary(ProductSecondaryPage.BillSplits),
            mainProductDestination(ProductSecondaryPage.BillSplits.route),
        )
        assertEquals(
            MainProductDestination.Secondary(ProductSecondaryPage.InsightsDataQuality),
            mainProductDestination(ProductSecondaryPage.InsightsDataQuality.route),
        )
        assertEquals(
            MainProductDestination.Secondary(ProductSecondaryPage.BudgetAdvice),
            mainProductDestination(ProductSecondaryPage.BudgetAdvice.route),
        )
        assertEquals(
            MainProductDestination.Secondary(ProductSecondaryPage.RepaymentDrafts),
            mainProductDestination(REPAYMENT_DRAFT_ROUTE),
        )
        assertEquals(MainProductDestination.Workspace, mainProductDestination(WORKSPACE_ROUTE))
        assertNull(mainProductDestination("product/not-a-route"))
    }

    @Test
    fun planAndExpenseMutationsInvalidateTheRightProductSummaries() {
        val state = MainShellState()

        state.markPlanDataChanged()

        assertEquals(1, state.planDataRevision)
        assertEquals(1, state.insightsDataRevision)

        state.markExpenseEditCompleted()

        assertEquals(1, state.planDataRevision)
        assertEquals(2, state.insightsDataRevision)
        assertEquals(1, state.expenseEditCompletionRevision)
    }

    @Test
    fun libraryMutationInvalidatesTransactionsVocabularyAndInsightsTogether() {
        val state = MainShellState()

        state.markTransactionVocabularyChanged()

        assertEquals(1, state.transactionVocabularyRevision)
        assertEquals(1, state.insightsDataRevision)
        assertEquals(0, state.planDataRevision)
        assertEquals(0, state.expenseEditCompletionRevision)
    }
}

class MainShellStateRaceTest {
    @Test
    fun lastPrimarySelectionWinsAfterEarlierRequestWasHandledBeforeDestinationSync() {
        val state = MainShellState()

        state.selectPrimaryDomain(PrimaryDomain.Plans.key)
        assertEquals(
            MainNavigationRequest.OpenDomain(PrimaryDomain.Plans),
            state.consumeNavigationRequest(),
        )

        state.selectPrimaryDomain(PrimaryDomain.Inbox.key)
        state.syncDestination(MainProductDestination.Domain(PrimaryDomain.Plans))

        assertEquals(PrimaryDomain.Inbox, state.selectedDomain)
        assertEquals(
            MainNavigationRequest.OpenDomain(PrimaryDomain.Inbox),
            state.consumeNavigationRequest(),
        )

        state.syncDestination(MainProductDestination.Domain(PrimaryDomain.Inbox))
        assertEquals(PrimaryDomain.Inbox, state.selectedDomain)

        val restoredState = MainShellState()
        restoredState.syncDestination(MainProductDestination.Domain(PrimaryDomain.Plans))
        restoredState.syncDestination(
            MainProductDestination.Secondary(ProductSecondaryPage.Budget),
        )
        restoredState.selectPrimaryDomain(PrimaryDomain.Transactions.key)
        restoredState.consumeNavigationRequest()
        restoredState.selectPrimaryDomain(PrimaryDomain.Plans.key)
        restoredState.consumeNavigationRequest()

        restoredState.syncDestination(
            MainProductDestination.Domain(PrimaryDomain.Transactions),
        )

        assertEquals(PrimaryDomain.Plans, restoredState.selectedDomain)
        restoredState.syncDestination(
            MainProductDestination.Secondary(ProductSecondaryPage.Budget),
        )
        assertEquals(PrimaryDomain.Plans, restoredState.selectedDomain)
    }
}

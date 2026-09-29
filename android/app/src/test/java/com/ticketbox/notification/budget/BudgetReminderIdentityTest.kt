package com.ticketbox.notification.budget

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlinx.coroutines.test.runTest

class BudgetReminderIdentityTest {
    @Test
    fun anotherPrincipalGetsTheSameMonthsReminderWithoutSharingThePreviousThrottleOrSentMarker() = runTest {
        val harness = CheckerHarness()
        harness.checker.checkNow("ledger-1")
        harness.ownerKey = "another-account"
        harness.checker.checkNow("ledger-1")
        harness.checker.checkNow("ledger-1")

        assertEquals(2, harness.sourceCalls)
        assertEquals(2, harness.dispatched.size)
        assertEquals(2, harness.store.sent.size)
    }
}

package com.ticketbox.ui.navigation

import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import kotlin.test.Test
import kotlin.test.assertEquals

class RecurringPaymentReviewStatusTest {
    @Test
    fun mapsEveryOutboxStatusToAnHonestExistingFact() {
        assertEquals(R.string.manual_submission_waiting, recurringPaymentReviewStatusRes(PendingMutationStatus.Pending))
        assertEquals(R.string.manual_submission_sending, recurringPaymentReviewStatusRes(PendingMutationStatus.InFlight))
        assertEquals(R.string.manual_submission_done, recurringPaymentReviewStatusRes(PendingMutationStatus.Done))
        assertEquals(R.string.sync_status_conflict_fallback, recurringPaymentReviewStatusRes(PendingMutationStatus.Conflict))
        assertEquals(R.string.sync_status_failed_fallback, recurringPaymentReviewStatusRes(PendingMutationStatus.Failed))
        assertEquals(R.string.recurring_payment_review_abandoned, recurringPaymentReviewStatusRes(PendingMutationStatus.Abandoned))
        assertEquals(R.string.manual_submission_unknown, recurringPaymentReviewStatusRes(PendingMutationStatus.Unknown))
    }
}

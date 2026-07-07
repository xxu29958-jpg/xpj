package com.ticketbox.ui.screens.pending

import com.ticketbox.domain.model.DuplicateStatusValues
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseSourceValues
import com.ticketbox.viewmodel.PendingListLoadState
import kotlin.test.Test
import kotlin.test.assertEquals

class PendingScreenModelsTest {

    @Test
    fun listBodyStateSeparatesLoadingFailedEmptyAndContent() {
        assertEquals(
            PendingListBodyState.Loading,
            pendingListBodyState(hasRows = false, loadState = PendingListLoadState.Unknown),
        )
        assertEquals(
            PendingListBodyState.Loading,
            pendingListBodyState(hasRows = false, loadState = PendingListLoadState.Loading),
        )
        assertEquals(
            PendingListBodyState.LoadFailed,
            pendingListBodyState(hasRows = false, loadState = PendingListLoadState.Failed),
        )
        assertEquals(
            PendingListBodyState.Empty,
            pendingListBodyState(hasRows = false, loadState = PendingListLoadState.Loaded),
        )
        assertEquals(
            PendingListBodyState.Content,
            pendingListBodyState(hasRows = true, loadState = PendingListLoadState.Failed),
        )
    }

    @Test
    fun primaryReviewActionFollowsPendingReviewPriority() {
        assertEquals(
            PendingPrimaryReviewAction.MissingAmount,
            pendingPrimaryReviewAction(pendingExpense(amountCents = null)),
        )
        assertEquals(
            PendingPrimaryReviewAction.DuplicateReview,
            pendingPrimaryReviewAction(
                pendingExpense(duplicateStatus = DuplicateStatusValues.SUSPECTED),
            ),
        )
        assertEquals(
            PendingPrimaryReviewAction.QuickCategory,
            pendingPrimaryReviewAction(pendingExpense(category = "")),
        )
        assertEquals(
            PendingPrimaryReviewAction.QuickMerchant,
            pendingPrimaryReviewAction(pendingExpense(merchant = "")),
        )
        assertEquals(
            PendingPrimaryReviewAction.Confirm,
            pendingPrimaryReviewAction(pendingExpense()),
        )
    }

    @Test
    fun primaryReviewActionKeepsEarlierBlockingWorkAheadOfLaterFields() {
        assertEquals(
            PendingPrimaryReviewAction.MissingAmount,
            pendingPrimaryReviewAction(
                pendingExpense(
                    amountCents = null,
                    merchant = "",
                    category = "",
                    duplicateStatus = DuplicateStatusValues.SUSPECTED,
                ),
            ),
        )
        assertEquals(
            PendingPrimaryReviewAction.DuplicateReview,
            pendingPrimaryReviewAction(
                pendingExpense(
                    merchant = "",
                    category = "",
                    duplicateStatus = DuplicateStatusValues.SUSPECTED,
                ),
            ),
        )
        assertEquals(
            PendingPrimaryReviewAction.QuickCategory,
            pendingPrimaryReviewAction(
                pendingExpense(
                    merchant = "",
                    category = "",
                ),
            ),
        )
    }
}

private fun pendingExpense(
    amountCents: Long? = 1280L,
    merchant: String? = "咖啡店",
    category: String = "餐饮",
    duplicateStatus: String = "",
): Expense = Expense(
    id = 1L,
    publicId = "pending-1",
    amountCents = amountCents,
    merchant = merchant,
    category = category,
    note = null,
    source = ExpenseSourceValues.ANDROID_SCREENSHOT,
    imagePath = null,
    thumbnailPath = null,
    imageHash = null,
    rawText = null,
    confidence = null,
    duplicateStatus = duplicateStatus,
    duplicateOfId = null,
    duplicateReason = null,
    tags = null,
    valueScore = null,
    regretScore = null,
    status = "pending",
    expenseTime = "2026-07-08T08:00:00Z",
    createdAt = "2026-07-08T08:00:00Z",
    updatedAt = "2026-07-08T08:00:00Z",
    rowVersion = 1L,
    confirmedAt = null,
    rejectedAt = null,
)

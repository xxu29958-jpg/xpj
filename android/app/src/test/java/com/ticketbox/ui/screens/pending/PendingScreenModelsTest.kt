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
        assertUncategorizedTokensEnterQuickCategory()
        assertEquals(
            PendingPrimaryReviewAction.QuickMerchant,
            pendingPrimaryReviewAction(pendingExpense(merchant = "")),
        )
        assertEquals(
            PendingPrimaryReviewAction.Confirm,
            pendingPrimaryReviewAction(pendingExpense()),
        )
        assertMerchantReviewClassification()
    }

    private fun assertUncategorizedTokensEnterQuickCategory() {
        listOf("未分类", "未分類", " none ", "NULL").forEach { category ->
            val expense = pendingExpense(category = category)
            assertEquals(
                PendingPrimaryReviewAction.QuickCategory,
                pendingPrimaryReviewAction(expense),
            )
            assertEquals(
                listOf(expense),
                applyNeedsReviewFilter(listOf(expense), NeedsReviewFilter.NeedsCategory),
            )
        }
    }

    private fun assertMerchantReviewClassification() {
        listOf(
            "12:34",
            "2026-07-17 12:34",
            "2026年7月17日 周五",
            "123456",
            "18:04 0",
            "18:02 0.00",
            "——",
            "A",
        ).forEach { merchant ->
            assertEquals(
                PendingPrimaryReviewAction.QuickMerchant,
                pendingPrimaryReviewAction(pendingExpense(merchant = merchant)),
                "OCR noise must enter the existing QuickMerchant flow: $merchant",
            )
            assertEquals(null, pendingMerchantPresentation(pendingExpense(merchant = merchant)).primaryText)
        }
        listOf("苏宁", "7-Eleven", "3M", "85度C", " 星巴克咖啡 ").forEach { merchant ->
            assertEquals(
                merchant.trim(),
                pendingMerchantPresentation(pendingExpense(merchant = merchant)).primaryText,
            )
        }
        val invalidMerchant = pendingExpense(merchant = "12:34")
        assertEquals(
            listOf(invalidMerchant),
            applyNeedsReviewFilter(listOf(invalidMerchant), NeedsReviewFilter.NeedsMerchant),
        )
        assertEquals(
            emptyList(),
            applyNeedsReviewFilter(listOf(invalidMerchant), NeedsReviewFilter.ReadyToConfirm),
        )
    }

    @Test
    fun merchantUsabilitySharedSamples() {
        // Shared with backend tests/test_data_quality_caliber_port.py — the
        // data-quality counters port this exact rule; any drift must redden
        // one of the two twins.
        listOf(
            null,
            "",
            "   ",
            "A", // single letter: < 2 meaningful chars
            "12", // digits only: no letter
            "12:34",
            "3:15 PM",
            "12:30:45",
            "2026-07-17 12:34",
            "2026年7月17日 周五",
            "7月22日",
            "123456",
            "18:04 0",
            "——",
        ).forEach { merchant ->
            assertEquals(
                null,
                pendingMerchantPresentation(pendingExpense(merchant = merchant)).primaryText,
                "must be unusable: $merchant",
            )
        }
        listOf("苏宁", "7-Eleven", "3M", "85度C", "星巴克咖啡", "A1", "ab", " 星巴克咖啡 ").forEach { merchant ->
            assertEquals(
                merchant.trim(),
                pendingMerchantPresentation(pendingExpense(merchant = merchant)).primaryText,
                "must be usable: $merchant",
            )
        }
    }

    @Test
    fun quickCategorySeesRawServerCategoryThroughNormalization() {
        // Display-normalized 「其他」 must not hide a server-side blank category
        // from the NeedsCategory surface (PR #230 round 4), and a raw
        // categorized value must not be misflagged either.
        val rawBlank = pendingExpense(category = "其他").copy(serverCategory = "")
        assertEquals(PendingPrimaryReviewAction.QuickCategory, pendingPrimaryReviewAction(rawBlank))
        assertEquals(listOf(rawBlank), applyNeedsReviewFilter(listOf(rawBlank), NeedsReviewFilter.NeedsCategory))

        val rawCategorized = pendingExpense(category = "其他").copy(serverCategory = "餐饮")
        assertEquals(PendingPrimaryReviewAction.Confirm, pendingPrimaryReviewAction(rawCategorized))
        assertEquals(
            emptyList(),
            applyNeedsReviewFilter(listOf(rawCategorized), NeedsReviewFilter.NeedsCategory),
        )

        // No raw value (manual construction): falls back to the display value.
        val legacy = pendingExpense(category = "未分类")
        assertEquals(PendingPrimaryReviewAction.QuickCategory, pendingPrimaryReviewAction(legacy))
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

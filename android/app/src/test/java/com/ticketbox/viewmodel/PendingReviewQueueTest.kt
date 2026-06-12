package com.ticketbox.viewmodel

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * [PendingReviewQueue] / [ReviewField] 纯函数口径直测（不经 VM / 协程）。
 *
 * 钉住连续审阅的下一条选择 + 「还剩 N 条」计数：列表顺序、当前票排除、跳过集排除、
 * 当前票之后无候选时的环绕、缺字段判定与列表/滑动同源。复用 [PendingViewModelReviewTestBase]
 * 的 [expense] 构造器，只为拿样本，不用计时器卫生 helper。
 */
internal class PendingReviewQueueTest : PendingViewModelReviewTestBase() {

    private fun missingMerchant(id: Long) = expense(id = id, merchant = null)
    private fun hasMerchant(id: Long) = expense(id = id, merchant = "已填")

    @Test
    fun reviewFieldMissingMatchesListAndSwipePredicates() {
        assertTrue(ReviewField.AMOUNT.isMissing(expense(id = 1L, amountCents = null)))
        assertTrue(!ReviewField.AMOUNT.isMissing(expense(id = 1L, amountCents = 100L)))

        assertTrue(ReviewField.MERCHANT.isMissing(expense(id = 1L, merchant = null)))
        assertTrue(ReviewField.MERCHANT.isMissing(expense(id = 1L, merchant = "   ")))
        assertTrue(!ReviewField.MERCHANT.isMissing(expense(id = 1L, merchant = "星巴克")))

        assertTrue(ReviewField.CATEGORY.isMissing(expense(id = 1L, category = "")))
        assertTrue(!ReviewField.CATEGORY.isMissing(expense(id = 1L, category = "餐饮")))
    }

    @Test
    fun remainingCountsMissingFieldExcludingSkipped() {
        val items = listOf(missingMerchant(1L), hasMerchant(2L), missingMerchant(3L), missingMerchant(4L))

        assertEquals(3, PendingReviewQueue.remaining(items, ReviewField.MERCHANT, emptySet()).size)
        // 跳过 1L → 还剩 3L、4L 两条（2L 本就不缺，不计）。
        assertEquals(2, PendingReviewQueue.remaining(items, ReviewField.MERCHANT, setOf(1L)).size)
    }

    @Test
    fun nextTargetPicksFollowingMissingTicketInListOrder() {
        val items = listOf(missingMerchant(1L), hasMerchant(2L), missingMerchant(3L), missingMerchant(4L))

        // 当前 1L → 跳过已填的 2L，取列表里其后的第一条缺商家票 3L。
        val next = PendingReviewQueue.nextTarget(items, ReviewField.MERCHANT, currentId = 1L, skippedIds = emptySet())
        assertEquals(3L, next?.id)
    }

    @Test
    fun nextTargetExcludesCurrentAndSkippedIds() {
        val items = listOf(missingMerchant(1L), missingMerchant(2L), missingMerchant(3L))

        // 当前 1L、已跳过 2L → 下一条只能是 3L。
        val next = PendingReviewQueue.nextTarget(items, ReviewField.MERCHANT, currentId = 1L, skippedIds = setOf(2L))
        assertEquals(3L, next?.id)
    }

    @Test
    fun nextTargetWrapsToEarlierCandidateWhenNoneFollow() {
        // 当前票排在最后，但前面还有一张缺商家的票 → 环绕取前面那条，不空转。
        val items = listOf(missingMerchant(1L), hasMerchant(2L), missingMerchant(3L))

        val next = PendingReviewQueue.nextTarget(items, ReviewField.MERCHANT, currentId = 3L, skippedIds = emptySet())
        assertEquals(1L, next?.id)
    }

    @Test
    fun nextTargetReturnsNullWhenQueueExhausted() {
        val items = listOf(missingMerchant(1L), hasMerchant(2L))

        // 唯一缺商家的就是当前 1L，排除自己后无候选 → 队列耗尽。
        assertNull(PendingReviewQueue.nextTarget(items, ReviewField.MERCHANT, currentId = 1L, skippedIds = emptySet()))
    }
}

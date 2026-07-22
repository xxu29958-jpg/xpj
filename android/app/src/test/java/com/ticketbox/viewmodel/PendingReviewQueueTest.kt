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
    fun dirtyCategoryTokenAndMerchantNoiseEnterTheirQueues() {
        // 与 QuickCategory/QuickMerchant 主判定同源（PR #230 round 8）：脏 token
        // 类目行必须进类目队列、噪音商家行必须进商家队列，不再被 isBlank 漏判。
        val dirtyTokenCategory = expense(id = 1L, category = "其他").copy(serverCategory = "none")
        val normalizedBlankCategory = expense(id = 2L, category = "其他").copy(serverCategory = "")
        val rawCleanCategory = expense(id = 3L, category = "其他").copy(serverCategory = "餐饮")
        assertTrue(ReviewField.CATEGORY.isMissing(dirtyTokenCategory))
        assertTrue(ReviewField.CATEGORY.isMissing(normalizedBlankCategory))
        assertTrue(!ReviewField.CATEGORY.isMissing(rawCleanCategory))

        val noiseMerchant = expense(id = 4L, merchant = "12:34")
        val singleLetterMerchant = expense(id = 5L, merchant = "A")
        val usableMerchant = expense(id = 6L, merchant = "3M")
        assertTrue(ReviewField.MERCHANT.isMissing(noiseMerchant))
        assertTrue(ReviewField.MERCHANT.isMissing(singleLetterMerchant))
        assertTrue(!ReviewField.MERCHANT.isMissing(usableMerchant))

        val categoryQueue = PendingReviewQueue.remaining(
            listOf(dirtyTokenCategory, rawCleanCategory),
            ReviewField.CATEGORY,
            emptySet(),
        )
        assertEquals(listOf(1L), categoryQueue.map { it.id })
        val merchantQueue = PendingReviewQueue.remaining(
            listOf(noiseMerchant, usableMerchant),
            ReviewField.MERCHANT,
            emptySet(),
        )
        assertEquals(listOf(4L), merchantQueue.map { it.id })
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

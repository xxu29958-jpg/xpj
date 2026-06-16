package com.ticketbox.ui.screens

import com.ticketbox.domain.model.DebtGoalLink
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertSame

/**
 * ADR-0049 §7.0 / 8e-6a 「先清小的」(snowball) 排序的纯函数单测（[sortedForPlan]）。
 * 纯客户端、对冻结快照算术、零 Compose 依赖。门控（composition == External）在调用方 [debtGoalDetailSection]，
 * 这里只钉排序语义本身。
 */
class DebtPlanSortTest {

    private fun link(
        id: String,
        status: String = "open",
        remaining: Long = 10_000,
    ) = DebtGoalLink(
        debtPublicId = id,
        status = status,
        direction = "i_owe",
        counterpartyType = "external",
        counterpartyLabel = null,
        principalAmountCents = remaining,
        remainingAmountCents = remaining,
        homeCurrencyCode = "CNY",
    )

    @Test
    fun defaultModeReturnsTheSameListUnchanged() {
        val links = listOf(link("a", remaining = 300), link("b", remaining = 100))
        val sorted = links.sortedForPlan(DebtPlanSortMode.Default)
        // Default 原样返回（同一实例，不复制不改序）。
        assertSame(links, sorted)
        assertEquals(listOf("a", "b"), sorted.map { it.debtPublicId })
    }

    @Test
    fun smallestRemainingFirstOrdersOpenDebtsAscending() {
        val links = listOf(
            link("c", remaining = 300),
            link("a", remaining = 100),
            link("b", remaining = 200),
        )
        val sorted = links.sortedForPlan(DebtPlanSortMode.SmallestRemainingFirst)
        assertEquals(listOf("a", "b", "c"), sorted.map { it.debtPublicId })
    }

    @Test
    fun smallestRemainingFirstSinksClearedThenVoidedBelowOpen() {
        val links = listOf(
            link("voided", status = "voided", remaining = 1),
            link("cleared", status = "cleared", remaining = 0),
            link("open-big", status = "open", remaining = 9_000),
            link("open-small", status = "open", remaining = 500),
        )
        val sorted = links.sortedForPlan(DebtPlanSortMode.SmallestRemainingFirst).map { it.debtPublicId }
        // 待清(按剩余升序) → 已两清 → 已作废。
        assertEquals(listOf("open-small", "open-big", "cleared", "voided"), sorted)
    }

    @Test
    fun smallestRemainingFirstClearedDoesNotFloatAboveOpen() {
        // 诚实点：cleared 的剩余为 0，但它是「已完成」不是「最该先清的」——绝不浮到开头（否则全列升序会误浮）。
        val links = listOf(
            link("cleared", status = "cleared", remaining = 0),
            link("open", status = "open", remaining = 5_000),
        )
        val sorted = links.sortedForPlan(DebtPlanSortMode.SmallestRemainingFirst).map { it.debtPublicId }
        assertEquals(listOf("open", "cleared"), sorted)
    }

    @Test
    fun smallestRemainingFirstKeepsStableOrderWithinResolvedBuckets() {
        val links = listOf(
            link("v2", status = "voided", remaining = 100),
            link("v1", status = "voided", remaining = 9_000),
            link("c2", status = "cleared", remaining = 0),
            link("c1", status = "cleared", remaining = 0),
            link("open", status = "open", remaining = 1),
        )
        val sorted = links.sortedForPlan(DebtPlanSortMode.SmallestRemainingFirst).map { it.debtPublicId }
        // 稳定排序：cleared/voided 桶内次键恒 0 → 保持各自源顺序（c2,c1 / v2,v1），不按剩余重排。
        assertEquals(listOf("open", "c2", "c1", "v2", "v1"), sorted)
    }

    @Test
    fun smallestRemainingFirstDoesNotMutateSource() {
        val links = listOf(
            link("c", remaining = 300),
            link("a", remaining = 100),
            link("b", remaining = 200),
        )
        links.sortedForPlan(DebtPlanSortMode.SmallestRemainingFirst)
        // 源 list 顺序保持不变（返回新列表，保 items(key=) 稳定）。
        assertEquals(listOf("c", "a", "b"), links.map { it.debtPublicId })
    }
}

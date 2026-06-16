package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/**
 * ADR-0049 §6 (slice 8e-5) 还债计划进度的纯派生属性单测（[DebtRepaymentEvaluation] / [DebtGoalLink]）。
 * 这些属性驱动件数进度 / 成分语气 / 金额副文案，全是冻结快照的纯客户端算术（零后端字段，零 Compose 依赖）。
 */
class DebtGoalProgressTest {

    private fun link(
        status: String,
        counterpartyType: String = "member",
        principal: Long = 10_000,
        remaining: Long = if (status == "cleared") 0L else 10_000,
        currency: String = "CNY",
    ) = DebtGoalLink(
        debtPublicId = "$counterpartyType-$status-$principal-$remaining-$currency",
        status = status,
        direction = "i_owe",
        counterpartyType = counterpartyType,
        counterpartyLabel = "小明",
        principalAmountCents = principal,
        remainingAmountCents = remaining,
        homeCurrencyCode = currency,
    )

    private fun eval(links: List<DebtGoalLink>) = DebtRepaymentEvaluation(
        goalVersion = 1,
        evaluationState = "in_progress",
        needsReview = false,
        achievedAt = null,
        achievedVersion = null,
        linkedDebts = links,
        voidedDebtPublicIds = links.filter { it.isVoided }.map { it.debtPublicId },
    )

    @Test
    fun compositionIsMemberWhenAllNonVoidedAreMembers() {
        val e = eval(listOf(link("cleared", "member"), link("open", "member")))
        assertEquals(DebtGoalComposition.Member, e.composition)
    }

    @Test
    fun compositionIsExternalWhenAllNonVoidedAreExternal() {
        val e = eval(listOf(link("cleared", "external"), link("open", "external")))
        assertEquals(DebtGoalComposition.External, e.composition)
    }

    @Test
    fun compositionIsMixedWhenBothTypesPresent() {
        val e = eval(listOf(link("open", "member"), link("open", "external")))
        assertEquals(DebtGoalComposition.Mixed, e.composition)
    }

    @Test
    fun compositionIsEmptyWhenEveryLinkVoided() {
        val e = eval(listOf(link("voided", "member"), link("voided", "external")))
        assertEquals(DebtGoalComposition.Empty, e.composition)
        assertEquals(0, e.totalCount)
        assertEquals(0f, e.planFraction)
    }

    @Test
    fun voidedLinkDoesNotFlipMemberCompositionToMixed() {
        // a voided external link must not be counted — composition stays Member (§6.2 voided excluded).
        val e = eval(listOf(link("cleared", "member"), link("voided", "external")))
        assertEquals(DebtGoalComposition.Member, e.composition)
    }

    @Test
    fun countsExcludeVoidedFromDenominatorButForgivenCountsAsCleared() {
        // cleared (incl. forgiven, which folds to cleared) counts; voided is out of the denominator.
        val e = eval(listOf(link("cleared", "member"), link("open", "member"), link("voided", "member")))
        assertEquals(1, e.clearedCount)
        assertEquals(2, e.totalCount)
        assertEquals(1, e.remainingCount)
        assertEquals(0.5f, e.planFraction)
    }

    @Test
    fun planFractionIsZeroWhenNothingCleared() {
        val e = eval(listOf(link("open", "member"), link("open", "member")))
        assertEquals(0, e.clearedCount)
        assertEquals(0f, e.planFraction)
    }

    @Test
    fun sharedCurrencyIsCodeWhenSingleAndNullWhenMixedCurrency() {
        assertEquals("CNY", eval(listOf(link("open", currency = "CNY"), link("cleared", currency = "CNY"))).sharedHomeCurrencyCode)
        assertNull(eval(listOf(link("open", currency = "CNY"), link("open", currency = "USD"))).sharedHomeCurrencyCode)
    }

    @Test
    fun sharedCurrencyIgnoresVoidedLinks() {
        // a voided link in another currency must not suppress the amount line (voided excluded, §6.2).
        val e = eval(listOf(link("open", currency = "CNY"), link("voided", currency = "USD")))
        assertEquals("CNY", e.sharedHomeCurrencyCode)
    }

    @Test
    fun amountSumsCoverOnlyNonVoidedLinks() {
        val e = eval(
            listOf(
                link("open", principal = 10_000, remaining = 4_000),
                link("cleared", principal = 5_000, remaining = 0),
                link("voided", principal = 9_999, remaining = 9_999),
            ),
        )
        assertEquals(15_000, e.principalSumCents)
        assertEquals(4_000, e.remainingSumCents)
    }

    @Test
    fun linkClearedFractionByAmount() {
        assertEquals(1f, link("cleared", principal = 10_000, remaining = 0).clearedFraction)
        assertEquals(0.6f, link("open", principal = 10_000, remaining = 4_000).clearedFraction)
        // degenerate principal <= 0 → 0 (no divide-by-zero), open with no progress → 0.
        assertEquals(0f, link("open", principal = 0, remaining = 0).clearedFraction)
        assertEquals(0f, link("open", principal = 10_000, remaining = 10_000).clearedFraction)
    }
}

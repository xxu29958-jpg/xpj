package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.remote.dto.DebtGoalLinkViewDto
import com.ticketbox.data.remote.dto.DebtGoalTargetDateRequestDto
import com.ticketbox.data.remote.dto.DebtRepaymentEvaluationDto
import com.ticketbox.data.remote.dto.GoalDto
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * ADR-0049 §6 (slice 7): the debt_repayment goal DTO → domain mapping. A debt goal's
 * spending-shape fields are null on the wire and coalesce to 0 / "" so the domain
 * [com.ticketbox.domain.model.Goal] stays non-null for the spending-goal UI, while the
 * nested evaluation block carries the real debt state.
 */
class DebtGoalMappersTest {

    @Test
    fun debtGoalDtoCoalescesNullSpendFieldsAndMapsEvaluation() {
        val domain = debtGoalDto().toDomain()

        assertTrue(domain.isDebtRepayment)
        // null spend fields coalesce — the debt UI ignores these and reads debtRepayment.
        assertEquals("", domain.month)
        assertEquals(0L, domain.targetAmountCents)
        assertEquals(0L, domain.spentAmountCents)
        assertEquals(0L, domain.remainingAmountCents)
        assertEquals(0, domain.progressPercent)

        val evaluation = requireNotNull(domain.debtRepayment)
        assertEquals(2, evaluation.goalVersion)
        assertTrue(evaluation.isInProgress)
        assertFalse(evaluation.isAchieved)
        assertEquals(2, evaluation.linkedDebts.size)
        assertEquals(listOf("debt-b"), evaluation.voidedDebtPublicIds)
    }

    @Test
    fun evaluationHelpersPartitionLinksByFoldStatus() {
        val evaluation = requireNotNull(debtGoalDto().toDomain().debtRepayment)

        assertEquals(listOf("debt-a"), evaluation.openDebts.map { it.debtPublicId })
        assertEquals(listOf("debt-b"), evaluation.voidedDebts.map { it.debtPublicId })
        // the non-voided set is what the link-replace integrity exit submits.
        assertEquals(listOf("debt-a"), evaluation.nonVoidedDebtPublicIds)

        val open = evaluation.linkedDebts.first { it.debtPublicId == "debt-a" }
        assertTrue(open.isOpen)
        assertFalse(open.isVoided)
        assertEquals("i_owe", open.direction)
        assertEquals("external", open.counterpartyType)

        val voided = evaluation.linkedDebts.first { it.debtPublicId == "debt-b" }
        assertTrue(voided.isVoided)
        assertFalse(voided.isCleared)
    }

    @Test
    fun achievedEvaluationReportsAchievedAndKeepsLatchFields() {
        val achieved = DebtRepaymentEvaluationDto(
            goalVersion = 5,
            evaluationState = "achieved",
            needsReview = false,
            achievedAt = "2026-06-15T00:00:00Z",
            achievedVersion = 5,
            linkedDebts = listOf(
                DebtGoalLinkViewDto(
                    debtPublicId = "debt-x",
                    status = "cleared",
                    direction = "owed_to_me",
                    counterpartyType = "member",
                    counterpartyLabel = "家人",
                    principalAmountCents = 20000,
                    remainingAmountCents = 0,
                    homeCurrencyCode = "CNY",
                ),
            ),
            voidedDebtPublicIds = emptyList(),
        ).toDomain()

        assertTrue(achieved.isAchieved)
        assertFalse(achieved.needsReview)
        assertEquals(5, achieved.achievedVersion)
        assertEquals("2026-06-15T00:00:00Z", achieved.achievedAt)
        assertTrue(achieved.linkedDebts.single().isCleared)
        assertTrue(achieved.voidedDebts.isEmpty())
    }

    @Test
    fun evaluationMapsExternalKpiProjectionFields() {
        // 8e-6b: a pure-external plan carries the payoff projection on the wire.
        val domain = DebtRepaymentEvaluationDto(
            goalVersion = 1,
            evaluationState = "in_progress",
            needsReview = false,
            achievedAt = null,
            achievedVersion = null,
            linkedDebts = emptyList(),
            voidedDebtPublicIds = emptyList(),
            trackingDays = 60,
            projectedPayoffDate = "2026-09-01",
        ).toDomain()

        assertEquals(60, domain.trackingDays)
        assertEquals("2026-09-01", domain.projectedPayoffDate)
    }

    @Test
    fun evaluationKpiFieldsDefaultNullWhenAbsent() {
        // member / mixed / thin plans omit the projection + three-state (server-gated) → null on the domain.
        val domain = requireNotNull(debtGoalDto().toDomain().debtRepayment)
        assertNull(domain.trackingDays)
        assertNull(domain.projectedPayoffDate)
        assertNull(domain.targetDate)
        assertNull(domain.threeState)
    }

    @Test
    fun evaluationMapsTargetDateAndThreeStateFields() {
        // 8e-6c: a pure-external plan with a deadline carries target_date + three_state on the wire.
        val domain = DebtRepaymentEvaluationDto(
            goalVersion = 1,
            evaluationState = "in_progress",
            needsReview = false,
            achievedAt = null,
            achievedVersion = null,
            linkedDebts = emptyList(),
            voidedDebtPublicIds = emptyList(),
            trackingDays = 60,
            projectedPayoffDate = "2026-09-01",
            targetDate = "2026-12-01",
            threeState = "ahead",
        ).toDomain()

        assertEquals("2026-12-01", domain.targetDate)
        assertEquals("ahead", domain.threeState)
    }

    @Test
    fun spendingGoalDtoLeavesDebtRepaymentNull() {
        val domain = GoalDto(
            publicId = "goal-1",
            ledgerId = "owner",
            name = "本月餐饮",
            goalType = "spending_limit",
            period = "monthly",
            month = "2026-06",
            category = "吃饭",
            targetAmountCents = 80000,
            spentAmountCents = 64000,
            remainingAmountCents = 16000,
            progressPercent = 80,
            progressState = "near_limit",
            status = "active",
            createdAt = "2026-06-01T00:00:00Z",
            updatedAt = "2026-06-13T00:00:00Z",
            rowVersion = 1L,
            archivedAt = null,
        ).toDomain()

        assertFalse(domain.isDebtRepayment)
        assertNull(domain.debtRepayment)
        assertEquals("2026-06", domain.month)
        assertEquals(80000L, domain.targetAmountCents)
    }

    @Test
    fun targetDateRequestOmitsNullTargetDateForTheClearCase() {
        // The 8e-6c clear-deadline case relies on Moshi OMITTING target_date=null from the wire (the now-
        // optional backend field reads omitted == clear). Production Moshi (KotlinJsonAdapterFactory, no
        // serializeNulls — ApiClient) omits nulls; pin it so a future Moshi config change can't silently
        // break the clear case. (Set case: target_date present.)
        val adapter = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
            .adapter(DebtGoalTargetDateRequestDto::class.java)

        val setJson = adapter.toJson(DebtGoalTargetDateRequestDto(expectedRowVersion = 7L, targetDate = "2026-12-01"))
        assertTrue(setJson.contains("\"target_date\":\"2026-12-01\""))

        val clearJson = adapter.toJson(DebtGoalTargetDateRequestDto(expectedRowVersion = 7L, targetDate = null))
        assertTrue(clearJson.contains("\"expected_row_version\":7"))
        assertFalse(clearJson.contains("target_date"))
    }

    private fun debtGoalDto(): GoalDto = GoalDto(
        publicId = "debt-goal-1",
        ledgerId = "owner",
        name = "还清欠款",
        goalType = "debt_repayment",
        period = "monthly",
        month = null,
        category = null,
        targetAmountCents = null,
        spentAmountCents = null,
        remainingAmountCents = null,
        progressPercent = null,
        progressState = "in_progress",
        status = "active",
        createdAt = "2026-06-13T00:00:00Z",
        updatedAt = "2026-06-15T00:00:00Z",
        rowVersion = 3L,
        archivedAt = null,
        debtRepayment = DebtRepaymentEvaluationDto(
            goalVersion = 2,
            evaluationState = "in_progress",
            needsReview = false,
            achievedAt = null,
            achievedVersion = null,
            linkedDebts = listOf(
                DebtGoalLinkViewDto(
                    debtPublicId = "debt-a",
                    status = "open",
                    direction = "i_owe",
                    counterpartyType = "external",
                    counterpartyLabel = "招商信用卡",
                    principalAmountCents = 100000,
                    remainingAmountCents = 40000,
                    homeCurrencyCode = "CNY",
                ),
                DebtGoalLinkViewDto(
                    debtPublicId = "debt-b",
                    status = "voided",
                    direction = "owed_to_me",
                    counterpartyType = "member",
                    counterpartyLabel = "家人",
                    principalAmountCents = 50000,
                    remainingAmountCents = 50000,
                    homeCurrencyCode = "CNY",
                ),
            ),
            voidedDebtPublicIds = listOf("debt-b"),
        ),
    )
}

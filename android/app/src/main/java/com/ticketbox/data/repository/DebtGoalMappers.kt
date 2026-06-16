package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.DebtGoalLinkViewDto
import com.ticketbox.data.remote.dto.DebtRepaymentEvaluationDto
import com.ticketbox.domain.model.DebtGoalLink
import com.ticketbox.domain.model.DebtRepaymentEvaluation

/** ADR-0049 §6 (slice 7): DTO → domain for the debt_repayment goal evaluation block. */
fun DebtRepaymentEvaluationDto.toDomain(): DebtRepaymentEvaluation = DebtRepaymentEvaluation(
    goalVersion = goalVersion,
    evaluationState = evaluationState,
    needsReview = needsReview,
    achievedAt = achievedAt,
    achievedVersion = achievedVersion,
    linkedDebts = linkedDebts.map { it.toDomain() },
    voidedDebtPublicIds = voidedDebtPublicIds,
    trackingDays = trackingDays,
    projectedPayoffDate = projectedPayoffDate,
    targetDate = targetDate,
    threeState = threeState,
)

fun DebtGoalLinkViewDto.toDomain(): DebtGoalLink = DebtGoalLink(
    debtPublicId = debtPublicId,
    status = status,
    direction = direction,
    counterpartyType = counterpartyType,
    counterpartyLabel = counterpartyLabel,
    principalAmountCents = principalAmountCents,
    remainingAmountCents = remainingAmountCents,
    homeCurrencyCode = homeCurrencyCode,
)

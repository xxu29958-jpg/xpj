package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.IncomePlanCreateRequestDto
import com.ticketbox.data.remote.dto.IncomePlanDto
import com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomePlanStatus
import com.ticketbox.domain.model.IncomeSourceType

fun IncomePlanDto.toDomain(): IncomePlan = IncomePlan(
    publicId = publicId,
    label = label,
    sourceType = IncomeSourceType.fromWire(sourceType),
    frequency = IncomeFrequency.fromWire(frequency),
    incomeMonth = incomeMonth,
    amountCents = amountCents,
    payDay = payDay,
    status = IncomePlanStatus.fromWire(status),
    createdAt = createdAt,
    updatedAt = updatedAt,
    rowVersion = rowVersion,
    archivedAt = archivedAt,
)

data class IncomePlanDraft(
    val label: String,
    val sourceType: IncomeSourceType,
    val frequency: IncomeFrequency = IncomeFrequency.MONTHLY,
    val incomeMonth: String? = null,
    val amountCents: Long,
    val payDay: Int,
)

fun IncomePlanDraft.toCreateRequest(): IncomePlanCreateRequestDto =
    IncomePlanCreateRequestDto(
        label = label.trim(),
        sourceType = sourceType.wireValue,
        frequency = frequency.wireValue,
        incomeMonth = incomeMonthForWire(),
        amountCents = amountCents,
        payDay = payDay,
    )

data class IncomePlanPatch(
    val expectedRowVersion: Long,
    val label: String? = null,
    val sourceType: IncomeSourceType? = null,
    val frequency: IncomeFrequency? = null,
    val incomeMonth: String? = null,
    val amountCents: Long? = null,
    val payDay: Int? = null,
)

fun IncomePlanPatch.toUpdateRequest(): IncomePlanUpdateRequestDto =
    IncomePlanUpdateRequestDto(
        expectedRowVersion = expectedRowVersion,
        label = label?.trim(),
        sourceType = sourceType?.wireValue,
        frequency = frequency?.wireValue,
        incomeMonth = incomeMonth?.trim(),
        amountCents = amountCents,
        payDay = payDay,
    )

private fun IncomePlanDraft.incomeMonthForWire(): String? =
    if (frequency == IncomeFrequency.ONE_TIME) incomeMonth?.trim() else null
